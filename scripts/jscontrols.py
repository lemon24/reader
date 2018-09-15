from flask import Flask, request, redirect, flash, jsonify
import werkzeug

import sys
import os.path

root_dir = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(root_dir, '../src'))

from reader.app import get_flashed_messages_by_prefix, APIThing, APIError


app = Flask(
    __name__,
    template_folder='../src/reader/app/templates',
    static_folder='../src/reader/app/static',
)
app.secret_key = 'secret'
app.template_global()(get_flashed_messages_by_prefix)


@app.route('/')
def root():
    return app.jinja_env.from_string("""

{% import "macros.html" as macros %}

<!doctype html>

<meta name="viewport" content="width=device-width" />
<link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
<script src="{{ url_for('static', filename='controls.js') }}"></script>


<script>

window.onload = function () {

    register_all({{ url_for('form') | tojson | safe }});

};

</script>


<form action="{{ url_for('form') }}" method="post">
<ul class="controls">

{% call macros.simple_button('simple', 'simple', next=url_for('root', from_action='next-simple')) %}
    document.querySelector('#out').innerHTML = JSON.stringify(data);
{% endcall %}
{% call macros.confirm_button('confirm', 'confirm', 'confirm', next=url_for('root', from_action='next-confirm')) %}
    document.querySelector('#out').innerHTML = JSON.stringify(data);
{% endcall %}
{% call macros.text_input_button('text', 'text', 'text', 'text', next=url_for('root', from_action='next-text')) %}
    document.querySelector('#out').innerHTML = JSON.stringify(data);
{% endcall %}

{% call macros.simple_button('simple', 'simple2', leave_disabled=true, next=url_for('root', from_action='next-simple2')) %}
    document.querySelector('#out').innerHTML = "v2: " + JSON.stringify(data);
{% endcall %}
{% call macros.confirm_button('confirm', 'confirm2', 'confirm2', leave_disabled=true, next=url_for('root', from_action='next-confirm2')) %}
    document.querySelector('#out').innerHTML = "v2: " + JSON.stringify(data);
{% endcall %}
{% call macros.text_input_button('text', 'text2', 'text', 'text', leave_disabled=true, next=url_for('root', from_action='next-text2')) %}
    document.querySelector('#out').innerHTML = "v2: " + JSON.stringify(data);
{% endcall %}

{{ macros.simple_button('simple', 'simple3', next=url_for('root', from_action='next-simple3')) }}
{{ macros.confirm_button('confirm', 'confirm3', 'confirm3', next=url_for('root', from_action='next-confirm3')) }}
{{ macros.text_input_button('text', 'text3', 'text', 'text', next=url_for('root', from_action='next-text3')) }}

{% call macros.simple_button('simple-next', 'simple next') %}
    document.querySelector('#out').innerHTML = JSON.stringify(data);
{% endcall %}


{% for message in get_flashed_messages_by_prefix(
    'simple',
    'confirm',
    'text',
) %}
<li class="error">{{ message }}
{% endfor %}

</ul>

<input type="hidden" name="next" value='{{ url_for('root', from='next') }}'>

</form>


{% for message in get_flashed_messages_by_prefix('message') %}
<pre>{{ message }}</pre>
{% endfor %}

<pre id='out'></pre>


""").render()





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


