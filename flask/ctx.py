# -*- coding: utf-8 -*-
"""
    flask.ctx
    ~~~~~~~~~

    Implements the objects required to keep the context.
    实现对象以保持上下文内容

    :copyright: (c) 2015 by Armin Ronacher.
    :license: BSD, see LICENSE for more details.
"""

import sys
from functools import update_wrapper

from werkzeug.exceptions import HTTPException

from .globals import _request_ctx_stack, _app_ctx_stack
from .signals import appcontext_pushed, appcontext_popped
from ._compat import BROKEN_PYPY_CTXMGR_EXIT, reraise


# a singleton sentinel value for parameter defaults
_sentinel = object()


class _AppCtxGlobals(object):
    """A plain object."""

    def get(self, name, default=None):
        return self.__dict__.get(name, default)

    def pop(self, name, default=_sentinel):
        if default is _sentinel:
            return self.__dict__.pop(name)
        else:
            return self.__dict__.pop(name, default)

    def setdefault(self, name, default=None):
        return self.__dict__.setdefault(name, default)

    def __contains__(self, item):
        return item in self.__dict__

    def __iter__(self):
        return iter(self.__dict__)

    def __repr__(self):
        top = _app_ctx_stack.top
        if top is not None:
            return '<flask.g of %r>' % top.app.name
        return object.__repr__(self)


def after_this_request(f):
    """Executes a function after this request.  This is useful to modify
    response objects.  The function is passed the response object and has
    to return the same or a new one.
    在这个请求之后运行函数。这在修改响应对象时非常有用。会将响应对象传递给这个函数，
    这个函数处理后将会返回一个新的或者相同的响应对象。

    Example::

        @app.route('/')
        def index():
            @after_this_request
            def add_header(response):
                response.headers['X-Foo'] = 'Parachute'
                return response
            return 'Hello World!'

    This is more useful if a function other than the view function wants to
    modify a response.  For instance think of a decorator that wants to add
    some headers without converting the return value into a response object.

    .. versionadded:: 0.9
    """
    _request_ctx_stack.top._after_request_functions.append(f)
    return f


def copy_current_request_context(f):
    """A helper function that decorates a function to retain the current
    request context.  This is useful when working with greenlets.  The moment
    the function is decorated a copy of the request context is created and
    then pushed when the function is called.
    一个可以装饰函数可以保持住当前请求上下文。这在使用 greenlets 时非常有用。在函数被装饰的时候，
    一个请求的上下文对象呗创建，当函数被调用时，这个上下文对象会被 push 出来。

    Example::

        import gevent
        from flask import copy_current_request_context

        @app.route('/')
        def index():
            @copy_current_request_context
            def do_some_work():
                # do some work here, it can access flask.request like you
                # would otherwise in the view function.
                ...
            gevent.spawn(do_some_work)   # 此处可以异步地执行一些请求对象。
            return 'Regular response'

    .. versionadded:: 0.10
    """
    top = _request_ctx_stack.top
    if top is None:
        raise RuntimeError('This decorator can only be used at local scopes '
            'when a request context is on the stack.  For instance within '
            'view functions.')
    reqctx = top.copy()
    def wrapper(*args, **kwargs):
        with reqctx:
            return f(*args, **kwargs)
    return update_wrapper(wrapper, f)


def has_request_context():
    """If you have code that wants to test if a request context is there or
    not this function can be used.  For instance, you may want to take advantage
    of request information if the request object is available, but fail
    silently if it is unavailable.
    如果你需要测试一个请求上下文是否存在，这个函数可以使用。

    ::

        class User(db.Model):

            def __init__(self, username, remote_addr=None):
                self.username = username
                if remote_addr is None and has_request_context():
                    remote_addr = request.remote_addr
                self.remote_addr = remote_addr

    Alternatively you can also just test any of the context bound objects
    (such as :class:`request` or :class:`g` for truthness)::

        class User(db.Model):

            def __init__(self, username, remote_addr=None):
                self.username = username
                if remote_addr is None and request:
                    remote_addr = request.remote_addr
                self.remote_addr = remote_addr

    .. versionadded:: 0.7
    """
    return _request_ctx_stack.top is not None


def has_app_context():
    """Works like :func:`has_request_context` but for the application
    context.  You can also just do a boolean check on the
    :data:`current_app` object instead.
    和 current_app 是否存在是一致的。

    .. versionadded:: 0.9
    """
    return _app_ctx_stack.top is not None


class AppContext(object):
    """The application context binds an application object implicitly
    to the current thread or greenlet, similar to how the
    :class:`RequestContext` binds request information.  The application
    context is also implicitly created if a request context is created
    but the application is not on top of the individual application
    context.
    应用上下文将应用对象绑定到当前的县线程或者 greenlet 中，和 :class:`RequestContext`
    类似，但是绑定的应用上下文信息。如果在创建 request context 时没有 app context，那么 app context
    会被自动创建。
    """

    def __init__(self, app):
        self.app = app
        self.url_adapter = app.create_url_adapter(None)
        self.g = app.app_ctx_globals_class()

        # Like request context, app contexts can be pushed multiple times
        # but there a basic "refcount" is enough to track them.
        self._refcnt = 0

    def push(self):
        """Binds the app context to the current context. 将自己绑定到当前的上下文中。
        """
        self._refcnt += 1                   # 每 push 一次，引用 +1
        if hasattr(sys, 'exc_clear'):
            sys.exc_clear()                 # 清除当前线程的异常信息
        _app_ctx_stack.push(self)
        appcontext_pushed.send(self.app)

    def pop(self, exc=_sentinel):
        """Pops the app context."""
        try:
            self._refcnt -= 1               # 每次 pop 引用计数减去 1ß
            if self._refcnt <= 0:
                if exc is _sentinel:
                    exc = sys.exc_info()[1]
                self.app.do_teardown_appcontext(exc)    # 这个 app 进行关闭上下文
        finally:
            rv = _app_ctx_stack.pop()
        assert rv is self, 'Popped wrong app context.  (%r instead of %r)' \
            % (rv, self)
        appcontext_popped.send(self.app)

    def __enter__(self):
        self.push()
        return self

    def __exit__(self, exc_type, exc_value, tb):
        self.pop(exc_value)

        if BROKEN_PYPY_CTXMGR_EXIT and exc_type is not None:
            reraise(exc_type, exc_value, tb)


class RequestContext(object):
    """The request context contains all request relevant information.  It is
    created at the beginning of the request and pushed to the
    `_request_ctx_stack` and removed at the end of it.  It will create the
    URL adapter and request object for the WSGI environment provided.
    request 上下文包括所有 request 相关的信息。他在每个 request 开始时创建，并压入到
    `_request_ctx_stack` 并且在请求结束时关闭。他将会创建 URL adapter 和 request 对象
    提供给 WSGI 环境。

    Do not attempt to use this class directly, instead use
    :meth:`~flask.Flask.test_request_context` and
    :meth:`~flask.Flask.request_context` to create this object.
    不要直接使用这个类，而是使用 :meth:`~flask.Flask.test_request_context`
    和 :meth:`~flask.Flask.request_context` 来创建这个对象。

    When the request context is popped, it will evaluate all the
    functions registered on the application for teardown execution
    (:meth:`~flask.Flask.teardown_request`).
    当请求上下文被 pop 后，他将会求值所有注册在 application 上的 teardown 函数。(:meth:`~flask.Flask.teardown_request`).


    The request context is automatically popped at the end of the request
    for you.  In debug mode the request context is kept around if
    exceptions happen so that interactive debuggers have a chance to
    introspect the data.  With 0.4 this can also be forced for requests
    that did not fail and outside of ``DEBUG`` mode.  By setting
    ``'flask._preserve_context'`` to ``True`` on the WSGI environment the
    context will not pop itself at the end of the request.  This is used by
    the :meth:`~flask.Flask.test_client` for example to implement the
    deferred cleanup functionality.
    在 debug 时，需要 request context 延迟进行清理，以定位错误。
    这时候可以使用 flask.test_client

    You might find this helpful for unittests where you need the
    information from the context local around for a little longer.  Make
    sure to properly :meth:`~werkzeug.LocalStack.pop` the stack yourself in
    that situation, otherwise your unittests will leak memory.
    注意，在使用 unittest 时避免内存泄露。
    """

    def __init__(self, app, environ, request=None):
        self.app = app
        if request is None:
            request = app.request_class(environ)
        self.request = request
        self.url_adapter = app.create_url_adapter(self.request)
        self.flashes = None
        self.session = None

        # Request contexts can be pushed multiple times and interleaved with | request context 可以被多次压入到栈中，并混杂在其它的 request 上下文中。
        # other request contexts.  Now only if the last level is popped we      | 只有当其最后的 pop 掉时，我们才不再需要他们。
        # get rid of them.  Additionally if an application context is missing   | 此外，如果应用上下文丢失，会隐式地创建一个新的。
        # one is created implicitly so for each level we add this information
        self._implicit_app_ctx_stack = []

        # indicator if the context was preserved.  Next time another context    | 指示 上下文是否可以保存。否则下一个上下文被压入栈时，目前的上下文会被弹出。
        # is pushed the preserved context is popped.
        self.preserved = False

        # remembers the exception for pop if there is one in case the context   | 记住异常
        # preservation kicks in.
        self._preserved_exc = None

        # Functions that should be executed after the request on the response   | 请求结束时要调用的函数
        # object.  These will be called before the regular "after_request"
        # functions.
        self._after_request_functions = []

        self.match_request()

    def _get_g(self):
        return _app_ctx_stack.top.g
    def _set_g(self, value):
        _app_ctx_stack.top.g = value
    g = property(_get_g, _set_g)
    del _get_g, _set_g

    def copy(self):
        """Creates a copy of this request context with the same request object.
        This can be used to move a request context to a different greenlet.
        Because the actual request object is the same this cannot be used to
        move a request context to a different thread unless access to the
        request object is locked.
        复制请求环境，用于将一个请求上下文移动到一个不同的 greenlet 中。因为真实的请求对象是相同的
        所以如果没有进行加锁，不能够从一个线程移动到另一个线程。

        .. versionadded:: 0.10
        """
        return self.__class__(self.app,
            environ=self.request.environ,
            request=self.request
        )

    def match_request(self):
        """Can be overridden by a subclass to hook into the matching
        of the request.
        可以由子类作为一个钩子进行覆盖，匹配请求。
        """
        try:
            url_rule, self.request.view_args = \
                self.url_adapter.match(return_rule=True)
            self.request.url_rule = url_rule
        except HTTPException as e:
            self.request.routing_exception = e

    def push(self):
        """Binds the request context to the current context. 将请求上下文绑定到当前的上下文中。"""
        # If an exception occurs in debug mode or if context preservation is
        # activated under exception situations exactly one context stays    当使用了 preservation 设置或者处于 debug 模式时
        # on the stack.  The rationale is that you want to access that      发生的 exception 会做为一个 stack 中的上下文。
        # information under debug situations.  However if someone forgets to    在调试时可能需要访问这些信息。如果忘记 pop，应该保证下次push
        # pop that context again we want to make sure that on the next push     时，他是无效的，否则就有可能出现内存泄露
        # it's invalidated, otherwise we run at risk that something leaks
        # memory.  This is usually only a problem in test suite since this
        # functionality is not active in production environments.
        top = _request_ctx_stack.top
        if top is not None and top.preserved:
            top.pop(top._preserved_exc)

        # Before we push the request context we have to ensure that there   如果在 push request context 时没有应用上下文会自动创建。
        # is an application context.
        app_ctx = _app_ctx_stack.top
        if app_ctx is None or app_ctx.app != self.app:      # 如果当前 app_ctx_stack 中没有 app 或者 top ctx 中的 app 不是请求对应的 ctx 中，将当前的 ctx (重新)入栈。
            app_ctx = self.app.app_context()
            app_ctx.push()
            self._implicit_app_ctx_stack.append(app_ctx)
        else:
            self._implicit_app_ctx_stack.append(None)       # 如果还是当前 request 对应的 app_ctx 在栈顶，压入一个  None。

        if hasattr(sys, 'exc_clear'):
            sys.exc_clear()

        _request_ctx_stack.push(self)

        # Open the session at the moment that the request context is        当 request 上下文可用时，打开 session。
        # available. This allows a custom open_session method to use the    这允许自定义一个 open_session 方法来使用 请求上下文。
        # request context (e.g. code that access database information       比如访问数据的代码替代 app_context 中的 g。
        # stored on `g` instead of the appcontext).
        self.session = self.app.open_session(self.request)
        if self.session is None:
            self.session = self.app.make_null_session()

    def pop(self, exc=_sentinel):
        """Pops the request context and unbinds it by doing that.  This will
        also trigger the execution of functions registered by the
        :meth:`~flask.Flask.teardown_request` decorator.
        将请求上下文对象出栈解除绑定。同时也会触发 `~flask.Flask.teardown_request`
        装饰器注册过的函数的调用。

        .. versionchanged:: 0.9
           Added the `exc` argument.
        """
        app_ctx = self._implicit_app_ctx_stack.pop()

        try:
            clear_request = False
            if not self._implicit_app_ctx_stack:
                self.preserved = False
                self._preserved_exc = None
                if exc is _sentinel:
                    exc = sys.exc_info()[1]
                self.app.do_teardown_request(exc)

                # If this interpreter supports clearing the exception information   如果需要清除异常信息，则马上做。
                # we do that now.  This will only go into effect on Python 2.x,     这只会在 Python 2.x 下起作用。
                # on 3.x it disappears automatically at the end of the exception
                # stack.
                if hasattr(sys, 'exc_clear'):
                    sys.exc_clear()

                request_close = getattr(self.request, 'close', None)        # 按需调用 request 的 close 方法。
                if request_close is not None:
                    request_close()
                clear_request = True
        finally:
            rv = _request_ctx_stack.pop()

            # get rid of circular dependencies at the end of the request
            # so that we don't require the GC to be active.
            if clear_request:
                rv.request.environ['werkzeug.request'] = None

            # Get rid of the app as well if necessary.
            if app_ctx is not None:
                app_ctx.pop(exc)

            assert rv is self, 'Popped wrong request context.  ' \
                '(%r instead of %r)' % (rv, self)

    def auto_pop(self, exc):
        if self.request.environ.get('flask._preserve_context') or \
           (exc is not None and self.app.preserve_context_on_exception):
            self.preserved = True
            self._preserved_exc = exc
        else:
            self.pop(exc)

    def __enter__(self):
        self.push()
        return self

    def __exit__(self, exc_type, exc_value, tb):
        # do not pop the request stack if we are in debug mode and an
        # exception happened.  This will allow the debugger to still        允许 debugger 在 交互的 shell 中访问 request 对象
        # access the request object in the interactive shell.  Furthermore  上下文也可以为 test_client 保持可用。
        # the context can be force kept alive for the test client.
        # See flask.testing for how this works.
        self.auto_pop(exc_value)

        if BROKEN_PYPY_CTXMGR_EXIT and exc_type is not None:
            reraise(exc_type, exc_value, tb)

    def __repr__(self):
        return '<%s \'%s\' [%s] of %s>' % (
            self.__class__.__name__,
            self.request.url,
            self.request.method,
            self.app.name,
        )
