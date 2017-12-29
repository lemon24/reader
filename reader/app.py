from flask import Flask, render_template, current_app
app = Flask(__name__)

@app.route('/')
def root():
    entries = current_app.reader.get_entries()
    return render_template('root.html', entries=entries)

