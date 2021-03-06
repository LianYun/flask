# -*- coding: utf-8 -*-
"""
    flask.wrappers
    ~~~~~~~~~~~~~~

    Implements the WSGI wrappers (request and response).

    :copyright: (c) 2015 by Armin Ronacher.
    :license: BSD, see LICENSE for more details.
"""

from werkzeug.wrappers import Request as RequestBase, Response as ResponseBase  
# 首先从werkzeug中导入请求和响应对象，继承实现修改。
from werkzeug.exceptions import BadRequest

from . import json
from .globals import _request_ctx_stack

_missing = object()


def _get_data(req, cache):
    getter = getattr(req, 'get_data', None)
    if getter is not None:
        return getter(cache=cache)
    return req.data


class Request(RequestBase):
    """The request object used by default in Flask.  Remembers the
    matched endpoint and view arguments.
    Flask中默认的请求对象。记住匹配的 endpoint 和视图参数。

    It is what ends up as :class:`~flask.request`.  If you want to replace
    the request object used you can subclass this and set
    :attr:`~flask.Flask.request_class` to your subclass.
    如果要自定义，可以创建这个类的子类，并且在 Flask 对象中替换 request_class

    The request object is a :class:`~werkzeug.wrappers.Request` subclass and
    provides all of the attributes Werkzeug defines plus a few Flask
    specific ones.
    这个请求对象是 `~werkzeug.wrappers.Request` 的子类。并且提供了所有的 Werkzeug 参数。
    """

    #: The internal URL rule that matched the request.  This can be
    #: useful to inspect which methods are allowed for the URL from
    #: a before/after handler (``request.url_rule.methods``) etc.
    #: 
    #: 内部的URL规则，匹配这个request。这个可以检查那个方法可以允许访问（通过before/after Handler）
    #: 
    #: .. versionadded:: 0.6
    url_rule = None

    #: A dict of view arguments that matched the request.  If an exception
    #: happened when matching, this will be ``None``.
    # 匹配这个请求的视图参数字典。如果一个异常在匹配时发生，这个将会设定为None。
    view_args = None

    #: If matching the URL failed, this is the exception that will be
    #: raised / was raised as part of the request handling.  This is
    #: usually a :exc:`~werkzeug.exceptions.NotFound` exception or
    #: something similar.
    # URL匹配失败时会抛出这个异常。
    routing_exception = None

    # Switched by the request context until 1.0 to opt in deprecated
    # module functionality.
    _is_old_module = False

    @property
    def max_content_length(self):
        """Read-only view of the `MAX_CONTENT_LENGTH` config key. 获得只读对象的包装 注意这种编程的方法。"""
        ctx = _request_ctx_stack.top
        if ctx is not None:
            return ctx.app.config['MAX_CONTENT_LENGTH']

    @property
    def endpoint(self):
        """The endpoint that matched the request.  This in combination with
        :attr:`view_args` can be used to reconstruct the same or a
        modified URL.  If an exception happened when matching, this will
        be ``None``.
        
        匹配请求的endpoit。
        """
        if self.url_rule is not None:
            return self.url_rule.endpoint

    @property
    def module(self):
        """The name of the current module if the request was dispatched
        to an actual module.  This is deprecated functionality, use blueprints
        instead.
        
        如果这个请求被分配给真实的module，这个就是当前模块的名字。 已经废除了这个方法，应该使用 blueprint 代替。
        """
        from warnings import warn
        warn(DeprecationWarning('modules were deprecated in favor of '
                                'blueprints.  Use request.blueprint '
                                'instead.'), stacklevel=2)
        if self._is_old_module:
            return self.blueprint

    @property
    def blueprint(self):
        """The name of the current blueprint. 当前的 blueprint"""
        if self.url_rule and '.' in self.url_rule.endpoint:
            return self.url_rule.endpoint.rsplit('.', 1)[0]

    @property
    def json(self):
        """If the mimetype is :mimetype:`application/json` this will contain the
        parsed JSON data.  Otherwise this will be ``None``.

        如果 mimetype 是 :mimetype:`application/json`, json 数据将会包括可以解析的 JSON 数据。
        The :meth:`get_json` method should be used instead.
        """
        from warnings import warn
        warn(DeprecationWarning('json is deprecated.  '
                                'Use get_json() instead.'), stacklevel=2)
        return self.get_json()

    @property
    def is_json(self):
        """Indicates if this request is JSON or not.  By default a request
        is considered to include JSON data if the mimetype is
        :mimetype:`application/json` or :mimetype:`application/*+json`.

        标识这个请求是不是 JSON。当一个请求的 mimetype 是 ``application/json`` 或者 ``application/*+json`` 时，请求可以包括JSON数据。
        .. versionadded:: 0.11
        """
        mt = self.mimetype
        if mt == 'application/json':
            return True
        if mt.startswith('application/') and mt.endswith('+json'):
            return True
        return False

    def get_json(self, force=False, silent=False, cache=True):
        """Parses the incoming JSON request data and returns it.  By default
        this function will return ``None`` if the mimetype is not
        :mimetype:`application/json` but this can be overridden by the
        ``force`` parameter. If parsing fails the
        :meth:`on_json_loading_failed` method on the request object will be
        invoked.

        解析收到的JSON请求，并且返回他。
        如果解析失败，那么回调用`on_json_loading_failed` 方法。
        应该先调用 is_json 检查，再做处理。

        :param force: if set to ``True`` the mimetype is ignored.
        :param silent: if set to ``True`` this method will fail silently
                       and return ``None``.
        :param cache: if set to ``True`` the parsed JSON data is remembered
        """
        rv = getattr(self, '_cached_json', _missing)
        # We return cached JSON only when the cache is enabled.
        if cache and rv is not _missing:
            return rv

        if not (force or self.is_json):     # 没有忽略类型且不是明确的json格式。
            return None

        # We accept a request charset against the specification as
        # certain clients have been using this in the past.  This
        # fits our general approach of being nice in what we accept
        # and strict in what we send out.
        request_charset = self.mimetype_params.get('charset')
        try:
            data = _get_data(self, cache)   # 从请求中获取数据
            if request_charset is not None:
                rv = json.loads(data, encoding=request_charset)
            else:
                rv = json.loads(data)
        except ValueError as e:
            if silent:
                rv = None
            else:
                rv = self.on_json_loading_failed(e)
        if cache:
            self._cached_json = rv
        return rv

    def on_json_loading_failed(self, e):
        """Called if decoding of the JSON data failed.  The return value of
        this method is used by :meth:`get_json` when an error occurred.  The
        default implementation just raises a :class:`BadRequest` exception.
        在解码json数据失败时调用。默认方法仅会抛出`BadRequest`异常。

        .. versionchanged:: 0.10
           Removed buggy previous behavior of generating a random JSON
           response.  If you want that behavior back you can trivially
           add it by subclassing.

        .. versionadded:: 0.8
        """
        ctx = _request_ctx_stack.top
        if ctx is not None and ctx.app.config.get('DEBUG', False):
            raise BadRequest('Failed to decode JSON object: {0}'.format(e))
        raise BadRequest()

    def _load_form_data(self):
        RequestBase._load_form_data(self)

        # In debug mode we're replacing the files multidict with an ad-hoc
        # subclass that raises a different error for key errors.
        ctx = _request_ctx_stack.top
        if ctx is not None and ctx.app.debug and \
           self.mimetype != 'multipart/form-data' and not self.files:
            from .debughelpers import attach_enctype_error_multidict
            attach_enctype_error_multidict(self)


class Response(ResponseBase):
    """The response object that is used by default in Flask.  Works like the
    response object from Werkzeug but is set to have an HTML mimetype by
    default.  Quite often you don't have to create this object yourself because
    :meth:`~flask.Flask.make_response` will take care of that for you.

    If you want to replace the response object used you can subclass this and
    set :attr:`~flask.Flask.response_class` to your subclass.
    可以通过创建这个类的子类，并将其赋值给 flask subclass 来自定义 Response
    """
    default_mimetype = 'text/html'
