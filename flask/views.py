# -*- coding: utf-8 -*-
"""
    flask.views
    ~~~~~~~~~~~

    This module provides class-based views inspired by the ones in Django.
    这个模块提供了基于类的视图，这个功能的添加受到了Django的启发。

    :copyright: (c) 2015 by Armin Ronacher.
    :license: BSD, see LICENSE for more details.
"""
from .globals import request
from ._compat import with_metaclass


http_method_funcs = frozenset(['get', 'post', 'head', 'options',
                               'delete', 'put', 'trace', 'patch'])


class View(object):
    """Alternative way to use view functions.  A subclass has to implement
    :meth:`dispatch_request` which is called with the view arguments from
    the URL routing system.  If :attr:`methods` is provided the methods
    do not have to be passed to the :meth:`~flask.Flask.add_url_rule`
    method explicitly::
    可替代的方式是使用视图函数。子类需要实现 dispatch_request 方法，URL的路由系统会自动以视图参数对这个方法进行调用。
    

        class MyView(View):
            methods = ['GET']

            def dispatch_request(self, name):
                return 'Hello %s!' % name

        app.add_url_rule('/hello/<name>', view_func=MyView.as_view('myview'))

    When you want to decorate a pluggable view you will have to either do that
    when the view function is created (by wrapping the return value of
    :meth:`as_view`) or you can use the :attr:`decorators` attribute::
    当你需要装饰一个插件的视图，你需要在视图函数创建的时候或者使用 decorators属性。

        class SecretView(View):
            methods = ['GET']
            decorators = [superuser_required]

            def dispatch_request(self):
                ...

    The decorators stored in the decorators list are applied one after another
    when the view function is created.  Note that you can *not* use the class
    based decorators since those would decorate the view class and not the
    generated view function!
    当视图函数创建时，装饰器中的函数会一个接一个地被调用。
    """

    #: 这个可插拔视图可以处理的方法.
    methods = None

    #: The canonical way to decorate class-based views is to decorate the
    #: return value of as_view().  However since this moves parts of the
    #: logic from the class declaration to the place where it's hooked
    #: into the routing system.
    #：一般的方式是装饰as_view函数的返回值。
    #:
    #: You can place one or more decorators in this list and whenever the
    #: view function is created the result is automatically decorated.
    #:
    #: .. versionadded:: 0.8
    decorators = ()

    def dispatch_request(self):
        """Subclasses have to override this method to implement the
        actual view function code.  This method is called with all
        the arguments from the URL rule.
        必须在子类实现时被覆盖。
        """
        raise NotImplementedError()

    @classmethod
    def as_view(cls, name, *class_args, **class_kwargs):
        """Converts the class into an actual view function that can be used
        with the routing system.  Internally this generates a function on the
        fly which will instantiate the :class:`View` on each request and call
        the :meth:`dispatch_request` method on it.
        将这个类转化为一个可被路由系统使用的视图函数。

        The arguments passed to :meth:`as_view` are forwarded to the
        constructor of the class.
        """
        def view(*args, **kwargs):
            self = view.view_class(*class_args, **class_kwargs)
            return self.dispatch_request(*args, **kwargs)

        if cls.decorators:
            view.__name__ = name
            view.__module__ = cls.__module__
            for decorator in cls.decorators:
                view = decorator(view)

        # We attach the view class to the view function for two reasons:
        # first of all it allows us to easily figure out what class-based
        # view this thing came from, secondly it's also used for instantiating
        # the view class so you can actually replace it with something else
        # for testing purposes and debugging.
        # 将这个类和返回的视图函数绑定起来，有助于我们找到生成的类。也可以用于实例化视图函数，可以在实际使用时进行替换，用于测试和debug。
        view.view_class = cls
        view.__name__ = name
        view.__doc__ = cls.__doc__
        view.__module__ = cls.__module__
        view.methods = cls.methods
        return view


class MethodViewType(type):
    """当python解释器在创建MethodView时，要通过MethodViewType.__new__，因而我们可以在此对类进行修改。
    """

    def __new__(cls, name, bases, d):
        """方法的参数依次是：
        1. 当前准备创建的类的对象。
        2. 类的名字。
        3. 类继承的父类集合。
        4. 类的方法集合。
        """
        rv = type.__new__(cls, name, bases, d)
        if 'methods' not in d:
            methods = set(rv.methods or [])
            for key in d:
                if key in http_method_funcs:
                    methods.add(key.upper())
            # If we have no method at all in there we don't want to
            # add a method list.  (This is for instance the case for
            # the base class or another subclass of a base method view
            # that does not introduce new methods).
            if methods:
                rv.methods = sorted(methods)
        return rv


class MethodView(with_metaclass(MethodViewType, View)):
    """Like a regular class-based view but that dispatches requests to
    particular methods.  For instance if you implement a method called
    :meth:`get` it means it will respond to ``'GET'`` requests and
    the :meth:`dispatch_request` implementation will automatically
    forward your request to that.  Also :attr:`options` is set for you
    automatically::
    和一个基于类的请求分配视图很类似，但是他将受到的HTTP 方法分配给类中对应签名的函数。

        class CounterAPI(MethodView):

            def get(self):
                return session.get('counter', 0)

            def post(self):
                session['counter'] = session.get('counter', 0) + 1
                return 'OK'

        app.add_url_rule('/counter', view_func=CounterAPI.as_view('counter'))
    """
    def dispatch_request(self, *args, **kwargs):
        meth = getattr(self, request.method.lower(), None)
        # If the request method is HEAD and we don't have a handler for it
        # retry with GET.
        if meth is None and request.method == 'HEAD':
            meth = getattr(self, 'get', None)
        assert meth is not None, 'Unimplemented method %r' % request.method     # 此处直接停止了程序？是不是有问题啊？
        return meth(*args, **kwargs)
