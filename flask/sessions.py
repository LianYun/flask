# -*- coding: utf-8 -*-
"""
    flask.sessions
    ~~~~~~~~~~~~~~

    Implements cookie based sessions based on itsdangerous.
    使用 itsdangerous 实现了基本的基于 cookie 的 session

    :copyright: (c) 2015 by Armin Ronacher.
    :license: BSD, see LICENSE for more details.
"""

import uuid
import hashlib
from base64 import b64encode, b64decode
from datetime import datetime
from werkzeug.http import http_date, parse_date
from werkzeug.datastructures import CallbackDict
from . import Markup, json
from ._compat import iteritems, text_type
from .helpers import total_seconds

from itsdangerous import URLSafeTimedSerializer, BadSignature


class SessionMixin(object):
    """Expands a basic dictionary with an accessors that are expected
    by Flask extensions and users for the session.
    扩展基本的字典，增加一个访问器，使得 Flask 的扩展和 session 的使用者可以得到更多的信息"""

    def _get_permanent(self):
        return self.get('_permanent', False)

    def _set_permanent(self, value):
        self['_permanent'] = bool(value)

    #: this reflects the ``'_permanent'`` key in the dict.
    permanent = property(_get_permanent, _set_permanent)
    del _get_permanent, _set_permanent

    #: some session backends can tell you if a session is new, but that is      一些 session 后台会告诉你 session 是新的
    #: not necessarily guaranteed.  Use with caution.  The default mixin        但是不会保证一定是成立的，使用时应当注意。默认
    #: implementation just hardcodes ``False`` in.                              实现只是简单地设定为 ``False`` 固定值。
    new = False

    #: for some backends this will always be ``True``, but some backends will
    #: default this to false and detect changes in the dictionary for as
    #: long as changes do not happen on mutable structures in the session.
    #: The default mixin implementation just hardcodes ``True`` in.
    modified = True


def _tag(value):
    if isinstance(value, tuple):
        return {' t': [_tag(x) for x in value]}
    elif isinstance(value, uuid.UUID):
        return {' u': value.hex}
    elif isinstance(value, bytes):
        return {' b': b64encode(value).decode('ascii')}
    elif callable(getattr(value, '__html__', None)):
        return {' m': text_type(value.__html__())}
    elif isinstance(value, list):
        return [_tag(x) for x in value]
    elif isinstance(value, datetime):
        return {' d': http_date(value)}
    elif isinstance(value, dict):
        return dict((k, _tag(v)) for k, v in iteritems(value))
    elif isinstance(value, str):
        try:
            return text_type(value)
        except UnicodeError:
            from flask.debughelpers import UnexpectedUnicodeError
            raise UnexpectedUnicodeError(u'A byte string with '
                u'non-ASCII data was passed to the session system '
                u'which can only store unicode strings.  Consider '
                u'base64 encoding your string (String was %r)' % value)
    return value


class TaggedJSONSerializer(object):
    """A customized JSON serializer that supports a few extra types that
    we take for granted when serializing (tuples, markup objects, datetime).
    一个自定义的 JSON 序列化器，支持元组、标记对象、时间等的序列化
    """

    def dumps(self, value):
        return json.dumps(_tag(value), separators=(',', ':'))

    LOADS_MAP = {
        ' t': tuple,
        ' u': uuid.UUID,
        ' b': b64decode,
        ' m': Markup,
        ' d': parse_date,
    }

    def loads(self, value):
        def object_hook(obj):
            if len(obj) != 1:
                return obj
            the_key, the_value = next(iteritems(obj))
            # Check the key for a corresponding function
            return_function = self.LOADS_MAP.get(the_key)
            if return_function:
                # Pass the value to the function
                return return_function(the_value)
            # Didn't find a function for this object
            return obj
        return json.loads(value, object_hook=object_hook)


session_json_serializer = TaggedJSONSerializer()


class SecureCookieSession(CallbackDict, SessionMixin):
    """Base class for sessions based on signed cookies.
    基本的 session 基类基于 登陆 cookies 来实现。
    """

    def __init__(self, initial=None):
        def on_update(self):
            self.modified = True
        # 若改变将 self.modified 设置为 True
        CallbackDict.__init__(self, initial, on_update)
        self.modified = False


class NullSession(SecureCookieSession):
    """Class used to generate nicer error messages if sessions are not
    available.  Will still allow read-only access to the empty session
    but fail on setting.
    用于 session 不可用时，生成良好的错误信息，可以访问空的 session 但是不能够设置
    """

    def _fail(self, *args, **kwargs):
        raise RuntimeError('The session is unavailable because no secret '
                           'key was set.  Set the secret_key on the '
                           'application to something unique and secret.')
    __setitem__ = __delitem__ = clear = pop = popitem = \
        update = setdefault = _fail
    del _fail


class SessionInterface(object):
    """The basic interface you have to implement in order to replace the
    default session interface which uses werkzeug's securecookie
    implementation.  The only methods you have to implement are
    :meth:`open_session` and :meth:`save_session`, the others have
    useful defaults which you don't need to change.
    如果要替代 werkzeug 的 securecookie，必须要实现的接口。需要自己实现的方法是：
    :meth:`open_session` 和 :meth:`save_session`，其他部分默认是不需要用户改变的。

    The session object returned by the :meth:`open_session` method has to
    provide a dictionary like interface plus the properties and methods
    from the :class:`SessionMixin`.  We recommend just subclassing a dict
    and adding that mixin (由 :meth:`open_session` 方法返回的 session object
    应当提供一个和字典类似的接口，扩展 :class:`SessionMixin` 的属性和方法。最简单的方法是继承
    dict 并增加 mixin。)::

        class Session(dict, SessionMixin):
            pass

    If :meth:`open_session` returns ``None`` Flask will call into
    :meth:`make_null_session` to create a session that acts as replacement
    if the session support cannot work because some requirement is not
    fulfilled.  The default :class:`NullSession` class that is created
    will complain that the secret key was not set.
    如果 :meth:`open_session` 返回 ``None`` Flask 将会调用 :meth:`make_null_session`
    来创建一个 session，用于 session 因为某些必要条件不支持时的补充。默认的 :class:`NullSession`
    将会创建一些警告来表示 secret key 没有设置的情况。

    To replace the session interface on an application all you have to do
    is to assign :attr:`flask.Flask.session_interface` 为了在应用中使用这个接口，需要给 :attr:`flask.Flask.session_interface`
    进行赋值如下::

        app = Flask(__name__)
        app.session_interface = MySessionInterface()

    .. versionadded:: 0.8
    """

    #: :meth:`make_null_session` will look here for the class that should
    #: be created when a null session is requested.  Likewise the
    #: :meth:`is_null_session` method will perform a typecheck against
    #: this type.
    null_session_class = NullSession

    #: A flag that indicates if the session interface is pickle based.
    #: This can be used by Flask extensions to make a decision in regards
    #: to how to deal with the session object.
    #:
    #: .. versionadded:: 0.10
    pickle_based = False

    def make_null_session(self, app):
        """Creates a null session which acts as a replacement object if the
        real session support could not be loaded due to a configuration
        error.  This mainly aids the user experience because the job of the
        null session is to still support lookup without complaining but
        modifications are answered with a helpful error message of what
        failed.
        创建一个 null session，如果真正的 session 因为配置不能加载，则使用这个
        session 作为占位符。

        This creates an instance of :attr:`null_session_class` by default.
        会默认创建一个 `null_session_class` 的实例。
        """
        return self.null_session_class()

    def is_null_session(self, obj):
        """Checks if a given object is a null session.  Null sessions are
        not asked to be saved.

        This checks if the object is an instance of :attr:`null_session_class`
        by default.
        """
        return isinstance(obj, self.null_session_class)

    def get_cookie_domain(self, app):
        """Helpful helper method that returns the cookie domain that should
        be used for the session cookie if session cookies are used.
        返回 cookie domain 的帮助方法。
        """
        if app.config['SESSION_COOKIE_DOMAIN'] is not None:
            return app.config['SESSION_COOKIE_DOMAIN']
        if app.config['SERVER_NAME'] is not None:
            # chop off the port which is usually not supported by browsers
            rv = '.' + app.config['SERVER_NAME'].rsplit(':', 1)[0]

            # Google chrome does not like cookies set to .localhost, so
            # we just go with no domain then.  Flask documents anyways that
            # cross domain cookies need a fully qualified domain name
            if rv == '.localhost':
                rv = None

            # If we infer the cookie domain from the server name we need
            # to check if we are in a subpath.  In that case we can't
            # set a cross domain cookie.
            if rv is not None:
                path = self.get_cookie_path(app)
                if path != '/':
                    rv = rv.lstrip('.')

            return rv

    def get_cookie_path(self, app):
        """Returns the path for which the cookie should be valid.  The
        default implementation uses the value from the ``SESSION_COOKIE_PATH``
        config var if it's set, and falls back to ``APPLICATION_ROOT`` or
        uses ``/`` if it's ``None``.
        """
        return app.config['SESSION_COOKIE_PATH'] or \
               app.config['APPLICATION_ROOT'] or '/'

    def get_cookie_httponly(self, app):
        """Returns True if the session cookie should be httponly.  This
        currently just returns the value of the ``SESSION_COOKIE_HTTPONLY``
        config var.
        """
        return app.config['SESSION_COOKIE_HTTPONLY']

    def get_cookie_secure(self, app):
        """Returns True if the cookie should be secure.  This currently
        just returns the value of the ``SESSION_COOKIE_SECURE`` setting.
        """
        return app.config['SESSION_COOKIE_SECURE']

    def get_expiration_time(self, app, session):
        """A helper method that returns an expiration date for the session
        or ``None`` if the session is linked to the browser session.  The
        default implementation returns now + the permanent session
        lifetime configured on the application.
        """
        if session.permanent:
            return datetime.utcnow() + app.permanent_session_lifetime

    def should_set_cookie(self, app, session):
        """Indicates whether a cookie should be set now or not.  This is
        used by session backends to figure out if they should emit a
        set-cookie header or not.  The default behavior is controlled by
        the ``SESSION_REFRESH_EACH_REQUEST`` config variable.  If
        it's set to ``False`` then a cookie is only set if the session is
        modified, if set to ``True`` it's always set if the session is
        permanent.
        如果 session 被修改了，那么进行更新
        如果设置每次请求更新 session 那么也对 session  进行更新。

        This check is usually skipped if sessions get deleted.

        .. versionadded:: 0.11
        """
        if session.modified:
            return True
        save_each = app.config['SESSION_REFRESH_EACH_REQUEST']
        return save_each and session.permanent

    def open_session(self, app, request):
        """This method has to be implemented and must either return ``None``
        in case the loading failed because of a configuration error or an
        instance of a session object which implements a dictionary like
        interface + the methods and attributes on :class:`SessionMixin`.
        这个方法或者返回 ``None``，或者一个实现了字典类似的接口，并拥有 :class:`SessionMixin`
        的全部属性和方法。
        """
        raise NotImplementedError()

    def save_session(self, app, session, response):
        """This is called for actual sessions returned by :meth:`open_session`
        at the end of the request.  This is still called during a request
        context so if you absolutely need access to the request you can do
        that.
        在每个 request 结束的时候，这个方法会被调用，当然也可以访问 request 本身进行调用。
        """
        raise NotImplementedError()


class SecureCookieSessionInterface(SessionInterface):
    """The default session interface that stores sessions in signed cookies
    through the :mod:`itsdangerous` module.
    """
    #: the salt that should be applied on top of the secret key for the
    #: signing of cookie based sessions.
    salt = 'cookie-session'
    #: the hash function to use for the signature.  The default is sha1
    digest_method = staticmethod(hashlib.sha1)
    #: the name of the itsdangerous supported key derivation.  The default
    #: is hmac.
    key_derivation = 'hmac'
    #: A python serializer for the payload.  The default is a compact
    #: JSON derived serializer with support for some extra Python types
    #: such as datetime objects or tuples.
    serializer = session_json_serializer        # 使用了上面给出的默认设置
    session_class = SecureCookieSession         # 使用了上面默认的 session 实现

    def get_signing_serializer(self, app):
        if not app.secret_key:
            return None
        signer_kwargs = dict(
            key_derivation=self.key_derivation,
            digest_method=self.digest_method
        )
        return URLSafeTimedSerializer(app.secret_key, salt=self.salt,
                                      serializer=self.serializer,
                                      signer_kwargs=signer_kwargs)

    def open_session(self, app, request):
        """
        1. 获取 cookie 解析器 -> URLSafeTimedSerializer
        2. 从 request 中获取 cookie， 没有 cookie 则返回空的 session
        3. 否则使用解析出的 data 构建一个 session
        :param app:
        :param request:
        :return:
        """
        s = self.get_signing_serializer(app)
        if s is None:
            return None
        val = request.cookies.get(app.session_cookie_name)
        if not val:
            return self.session_class()
        max_age = total_seconds(app.permanent_session_lifetime)
        try:
            data = s.loads(val, max_age=max_age)    # 直接从 cookie 中 loads 数据。
            return self.session_class(data)         # 使用 loads 的数据初始化 Session
        except BadSignature:
            return self.session_class()             # loads 失败也会返回空的 Session

    def save_session(self, app, session, response):
        """
        1. 获得当前 session 所在的 domain
        2. 获取当前 session 所在的 path
        3. 如果 session 已经被修改了，则 在 response 中先删除
        4. 满足更新条件，使用 httponly、secure、expires、val 进行更新
        :param app:
        :param session:
        :param response:
        :return:
        """
        domain = self.get_cookie_domain(app)
        path = self.get_cookie_path(app)

        # Delete case.  If there is no session we bail early.
        # If the session was modified to be empty we remove the
        # whole cookie.
        if not session:         # session 为空
            if session.modified:    # session 被修改了
                response.delete_cookie(app.session_cookie_name,
                                       domain=domain, path=path)
            return

        # Modification case.  There are upsides and downsides to
        # emitting a set-cookie header each request.  The behavior
        # is controlled by the :meth:`should_set_cookie` method
        # which performs a quick check to figure out if the cookie
        # should be set or not.  This is controlled by the
        # SESSION_REFRESH_EACH_REQUEST config flag as well as
        # the permanent flag on the session itself.
        if not self.should_set_cookie(app, session):    # 不满足更新条件
            return

        httponly = self.get_cookie_httponly(app)
        secure = self.get_cookie_secure(app)
        expires = self.get_expiration_time(app, session)
        val = self.get_signing_serializer(app).dumps(dict(session))
        response.set_cookie(app.session_cookie_name, val,               # 直接在响应的基础上增加 cookie 相关的内容
                            expires=expires, httponly=httponly,
                            domain=domain, path=path, secure=secure)
