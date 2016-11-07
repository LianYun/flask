# -*- coding: utf-8 -*-
"""
    flask.jsonimpl
    ~~~~~~~~~~~~~~

    Implementation helpers for the JSON support in Flask.

    :copyright: (c) 2015 by Armin Ronacher.
    :license: BSD, see LICENSE for more details.
"""
import io
import uuid
from datetime import date
from .globals import current_app, request
from ._compat import text_type, PY2

from werkzeug.http import http_date
from jinja2 import Markup

# Use the same json implementation as itsdangerous on which we
# depend anyways.
from itsdangerous import json as _json


# Figure out if simplejson escapes slashes.  This behavior was changed
# from one version to another without reason.
_slash_escape = '\\/' not in _json.dumps('/')


__all__ = ['dump', 'dumps', 'load', 'loads', 'htmlsafe_dump',
           'htmlsafe_dumps', 'JSONDecoder', 'JSONEncoder',
           'jsonify']


def _wrap_reader_for_text(fp, encoding):
    if isinstance(fp.read(0), bytes):
        fp = io.TextIOWrapper(io.BufferedReader(fp), encoding)
    return fp


def _wrap_writer_for_text(fp, encoding):
    try:
        fp.write('')
    except TypeError:
        fp = io.TextIOWrapper(fp, encoding)
    return fp


class JSONEncoder(_json.JSONEncoder):
    """The default Flask JSON encoder.  This one extends the default simplejson
    encoder by also supporting ``datetime`` objects, ``UUID`` as well as
    ``Markup`` objects which are serialized as RFC 822 datetime strings (same
    as the HTTP date format).  In order to support more data types override the
    :meth:`default` method.
    扩展了默认的 simplejson, 使得其支持 ``datetime`` 对象、`UUID`` 和 ``Markup`` objects。
    使用 RFC 822 的 HTTP 日期格式。
    """

    def default(self, o):
        """Implement this method in a subclass such that it returns a
        serializable object for ``o``, or calls the base implementation (to
        raise a :exc:`TypeError`).

        For example, to support arbitrary iterators, you could implement
        default like this::

            def default(self, o):
                try:
                    iterable = iter(o)
                except TypeError:
                    pass
                else:
                    return list(iterable)
                return JSONEncoder.default(self, o)
        """
        if isinstance(o, date):
            return http_date(o.timetuple())     # 转换日期格式
        if isinstance(o, uuid.UUID):
            return str(o)
        if hasattr(o, '__html__'):
            return text_type(o.__html__())
        return _json.JSONEncoder.default(self, o)


class JSONDecoder(_json.JSONDecoder):
    """The default JSON decoder.  This one does not change the behavior from
    the default simplejson decoder.  Consult the :mod:`json` documentation
    for more information.  This decoder is not only used for the load
    functions of this module but also :attr:`~flask.Request`.
    默认的 JSON decoder。这个没有改变默认的 simplejson decoder 的行为。
    """


def _dump_arg_defaults(kwargs):
    """Inject default arguments for dump functions."""
    if current_app:
        kwargs.setdefault('cls', current_app.json_encoder)
        if not current_app.config['JSON_AS_ASCII']:
            kwargs.setdefault('ensure_ascii', False)
        kwargs.setdefault('sort_keys', current_app.config['JSON_SORT_KEYS'])
    else:
        kwargs.setdefault('sort_keys', True)
        kwargs.setdefault('cls', JSONEncoder)


def _load_arg_defaults(kwargs):
    """Inject default arguments for load functions."""
    if current_app:
        kwargs.setdefault('cls', current_app.json_decoder)
    else:
        kwargs.setdefault('cls', JSONDecoder)


def dumps(obj, **kwargs):
    """Serialize ``obj`` to a JSON formatted ``str`` by using the application's
    configured encoder (:attr:`~flask.Flask.json_encoder`) if there is an
    application on the stack.
    如果在 stack 中存在一个 application 对象，使用应用配置的 encoder (:attr:`~flask.Flask.json_encoder`)
    序列化 ``obj`` 为一个  JSON 格式的 ``str``。

    This function can return ``unicode`` strings or ascii-only bytestrings by
    default which coerce into unicode strings automatically.  That behavior by
    default is controlled by the ``JSON_AS_ASCII`` configuration variable
    and can be overridden by the simplejson ``ensure_ascii`` parameter.

    """
    _dump_arg_defaults(kwargs)                              # 设置默认参数
    encoding = kwargs.pop('encoding', None)
    rv = _json.dumps(obj, **kwargs)                         # 先转化为字符串格式
    if encoding is not None and isinstance(rv, text_type):
        rv = rv.encode(encoding)                            # 再对字符串进行编码
    return rv


def dump(obj, fp, **kwargs):
    """Like :func:`dumps` but writes into a file object."""
    _dump_arg_defaults(kwargs)
    encoding = kwargs.pop('encoding', None)
    if encoding is not None:
        fp = _wrap_writer_for_text(fp, encoding)
    _json.dump(obj, fp, **kwargs)


def loads(s, **kwargs):
    """Unserialize a JSON object from a string ``s`` by using the application's
    configured decoder (:attr:`~flask.Flask.json_decoder`) if there is an
    application on the stack.
    """
    _load_arg_defaults(kwargs)
    if isinstance(s, bytes):
        s = s.decode(kwargs.pop('encoding', None) or 'utf-8')
    return _json.loads(s, **kwargs)


def load(fp, **kwargs):
    """Like :func:`loads` but reads from a file object.
    """
    _load_arg_defaults(kwargs)
    if not PY2:
        fp = _wrap_reader_for_text(fp, kwargs.pop('encoding', None) or 'utf-8')
    return _json.load(fp, **kwargs)


def htmlsafe_dumps(obj, **kwargs):
    """Works exactly like :func:`dumps` but is safe for use in ``<script>``
    tags.  It accepts the same arguments and returns a JSON string.  Note that
    this is available in templates through the ``|tojson`` filter which will
    also mark the result as safe.  Due to how this function escapes certain
    characters this is safe even if used outside of ``<script>`` tags.
    功能和 :func:`dumps` 类似，但是对于 ``<script>`` 标签是安全的

    The following characters are escaped in strings:

    -   ``<``
    -   ``>``
    -   ``&``
    -   ``'``

    This makes it safe to embed such strings in any place in HTML with the
    notable exception of double quoted attributes.  In that case single
    quote your attributes or HTML escape it in addition.

    .. versionchanged:: 0.10
       This function's return value is now always safe for HTML usage, even
       if outside of script tags or if used in XHTML.  This rule does not
       hold true when using this function in HTML attributes that are double
       quoted.  Always single quote attributes if you use the ``|tojson``
       filter.  Alternatively use ``|tojson|forceescape``.
    """
    rv = dumps(obj, **kwargs) \
        .replace(u'<', u'\\u003c') \
        .replace(u'>', u'\\u003e') \
        .replace(u'&', u'\\u0026') \
        .replace(u"'", u'\\u0027')
    if not _slash_escape:
        rv = rv.replace('\\/', '/')
    return rv


def htmlsafe_dump(obj, fp, **kwargs):
    """Like :func:`htmlsafe_dumps` but writes into a file object."""
    fp.write(text_type(htmlsafe_dumps(obj, **kwargs)))


def jsonify(*args, **kwargs):
    """This function wraps :func:`dumps` to add a few enhancements that make
    life easier.  It turns the JSON output into a :class:`~flask.Response`
    object with the :mimetype:`application/json` mimetype.  For convenience, it
    also converts multiple arguments into an array or multiple keyword arguments
    into a dict.  This means that both ``jsonify(1,2,3)`` and
    ``jsonify([1,2,3])`` serialize to ``[1,2,3]``.
    这个方法包装了 :func:`dumps`，做了一些增强，使得更加好用。将 JSON 输出为一个 :class:`~flask.Response`
    得到了一个 :mimetype:`application/json` mimetype。便利起见，他也可以将多个参数转化为一个数组，或者多个
    keyword 参数转化为一个字典。所以 jsonify(1, 2,3) 和 jsonify([1,2,3])都会转化为 [1, 2, 3]

    For clarity, the JSON serialization behavior has the following differences
    from :func:`dumps`:

    1. Single argument: Passed straight through to :func:`dumps`.   单个参数，直接传递给 :func:`dumps`。
    2. Multiple arguments: Converted to an array before being passed to
       :func:`dumps`. 多个参数， 在传递给 dumps 之前转化为一个数组。
    3. Multiple keyword arguments: Converted to a dict before being passed to
       :func:`dumps`. 多个键值对，在传递给 :func:`dumps` 之前转化为一个字典。
    4. Both args and kwargs: Behavior undefined and will throw an exception.
        同时有参数和键值参数，会抛出一个异常。

    Example usage::

        from flask import jsonify

        @app.route('/_get_current_user')
        def get_current_user():
            return jsonify(username=g.user.username,
                           email=g.user.email,
                           id=g.user.id)

    This will send a JSON response like this to the browser::

        {
            "username": "admin",
            "email": "admin@localhost",
            "id": 42
        }


    .. versionchanged:: 0.11
       Added support for serializing top-level arrays. This introduces a
       security risk in ancient browsers. See :ref:`json-security` for details.

    This function's response will be pretty printed if it was not requested
    with ``X-Requested-With: XMLHttpRequest`` to simplify debugging unless
    the ``JSONIFY_PRETTYPRINT_REGULAR`` config parameter is set to false.
    Compressed (not pretty) formatting currently means no indents and no
    spaces after separators.
    如果请求中不包含 ``X-Requested-With: XMLHttpRequest`` 并设置 ``JSONIFY_PRETTYPRINT_REGULAR``
    为 false，这个函数的响应会以良好的可打印格式展现来方便调试。压缩格式中不会包含空格和对齐。

    .. versionadded:: 0.2
    """

    indent = None
    separators = (',', ':')

    if current_app.config['JSONIFY_PRETTYPRINT_REGULAR'] and not request.is_xhr:
        indent = 2
        separators = (', ', ': ')

    if args and kwargs:
        raise TypeError('jsonify() behavior undefined when passed both args and kwargs')
    elif len(args) == 1:  # single args are passed directly to dumps()
        data = args[0]
    else:
        data = args or kwargs

    return current_app.response_class(
        (dumps(data, indent=indent, separators=separators), '\n'),
        mimetype=current_app.config['JSONIFY_MIMETYPE']
    )


def tojson_filter(obj, **kwargs):
    return Markup(htmlsafe_dumps(obj, **kwargs))
