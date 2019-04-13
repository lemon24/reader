"""
A thing to build APIs that work both with old-style forms and with JSON.

Contains no business logic.

See scripts/jscontrols.py for a minimal usage example.

"""

from urllib.parse import urlparse, urljoin

from flask import request, redirect, jsonify, flash, get_flashed_messages
import werkzeug


def is_safe_url(target):
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc


def redirect_to_referrer():
    if not request.referrer:
        return "no referrer", 400
    if not is_safe_url(request.referrer):
        return "bad referrer", 400
    return redirect(request.referrer)


def get_flashed_messages_by_prefix(*prefixes):
    messages = get_flashed_messages(with_categories=True)
    rv = []
    for pair in messages:
        category, message = pair
        if not isinstance(category, tuple):
            category = (category, )
        for prefix in prefixes:
            if not isinstance(prefix, tuple):
                prefix = (prefix, )
            category_prefix = category[:len(prefix)]
            if category_prefix == prefix:
                rv.append(message)
    return rv


class APIError(Exception):

    def __init__(self, message, category=None):
        super().__init__(message)
        self.message = message
        if category is not None:
            if not isinstance(category, tuple):
                category = (category, )
        self.category = category


class APIThing:

    def __init__(self, app_or_blueprint, rule, endpoint):
        self.actions = {}
        self.really = {}
        app_or_blueprint.add_url_rule(
            rule, endpoint, methods=['POST'], view_func=self.dispatch)
        (
            getattr(app_or_blueprint, 'add_app_template_global', None)
            or app_or_blueprint.add_template_global
        )(get_flashed_messages_by_prefix)

    def dispatch_form(self):
        action = request.form['action']
        func = self.actions.get(action)
        if func is None:
            return "unknown action", 400
        next = request.form.get('next-' + action)
        if next is None:
            next = request.form['next']
        if not is_safe_url(next):
            return "bad next", 400
        if self.really[func]:
            really = request.form.get('really-' + action)
            if really is None:
                really = request.form.get('really')
            target = request.form.get('target')
            if really != 'really':
                category = (action, )
                if target is not None:
                    category += (target, )
                flash("{}: really not checked".format(action), category)
                return redirect_to_referrer()
        try:
            rv = func(request.form)
            flash(rv)
        except APIError as e:
            category = (action, )
            if e.category:
                category += e.category
            flash("{}: {}".format(action, e), category)
            return redirect_to_referrer()
        return redirect(next)

    def dispatch_json(self):
        data = werkzeug.MultiDict(request.get_json())
        action = data['action']
        func = self.actions.get(action)
        if func is None:
            return "unknown action", 400

        try:
            rv = func(data)
            rv = {'ok': rv}
        except APIError as e:
            category = (action, )
            if e.category:
                category += e.category
            rv = {'err': e.message}

        return jsonify(rv)

    def dispatch(self):
        if request.mimetype == 'application/x-www-form-urlencoded':
            return self.dispatch_form()
        if request.mimetype == 'application/json':
            return self.dispatch_json()
        return "bad content type", 400

    def __call__(self, func=None, *, really=False):

        def register(f):
            self.actions[f.__name__.replace('_', '-')] = f
            self.really[f] = really
            return f

        if func is None:
            return register
        return register(func)


