from flask import Flask, render_template, current_app, send_from_directory
from flask_humanize import Humanize


app = Flask(__name__)
humanize = Humanize(app)


@app.route('/')
def root():
    entries = current_app.reader.get_entries()
    return render_template('root.html', entries=entries)

