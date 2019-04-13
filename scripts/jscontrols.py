from flask import Flask, request, redirect, flash, jsonify
import werkzeug

import sys
import os.path

root_dir = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(root_dir, '../src'))

from reader.app.api_thing import APIThing, APIError


app = Flask(
    __name__,
    template_folder='../src/reader/app/templates',
    static_folder='../src/reader/app/static',
)
app.secret_key = 'secret'


@app.route('/')
def root():
    with open(os.path.join(root_dir, 'jscontrols.html')) as f:
        template_string = f.read()
    return app.jinja_env.from_string(template_string).render()


form = APIThing(app, '/form', 'form')

@form
def simple(data):
    return 'simple'

@form
def simple_next(data):
    return 'simple-next: %s' % data['next']

@form(really=True)
def confirm(data):
    return 'confirm'

@form
def text(data):
    text = data['text']
    if text.startswith('err'):
        raise APIError(text, 'category')
    return 'text: %s' % text


