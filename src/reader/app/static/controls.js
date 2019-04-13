
// TODO: don't hardcode the li class=error bit
// TODO: no global state


JSON_REQUEST_TIMEOUT = 10000;
DONE_TIMEOUT = 1500;
ERROR_TIMEOUT = 2000;


function do_json_request(endpoint, data, callback, errback) {
    var xhr = new XMLHttpRequest();

    xhr.timeout = JSON_REQUEST_TIMEOUT;
    xhr.ontimeout = function () { errback("request: timeout"); };
    xhr.onerror = function () { errback("request: error"); };
    xhr.onabort = function () { errback("request: abort"); };

    xhr.onload = function () {
        if (xhr.status != 200) {
            errback("bad status code: " + xhr.status);
        }
        else {
            try {
                var data = JSON.parse(xhr.response);
            } catch (e) {
                errback("JSON parse error");
                return;
            }
            if ('err' in data && 'ok' in data) {
                errback("bad response: both ok and err");
            }
            else if ('err' in data) {
                errback(data.err);
            }
            else if ('ok' in data) {
                callback(data.ok);
            }
            else {
                errback("bad response: neither ok nor err");
            }
        };
    };

    xhr.open('POST', endpoint);
    xhr.setRequestHeader('Accept', 'application/json');
    xhr.setRequestHeader('Content-Type', 'application/json');

    try {
        var json_data = JSON.stringify(data);
    } catch (e) {
        errback("JSON stringify error");
        return;
    }
    xhr.send(json_data);
}


function register_simple(endpoint, collapsible, callback, errback) {
    if (collapsible.dataset.buttonType != 'simple') { return; }
    var button = collapsible.querySelector('button[name=action]');
    if (button === null) { return; };

    var state = 'none';
    var original_text = button.innerHTML;

    function reset_button () {
        state = 'none';
        button.innerHTML = original_text;
        if (collapsible.dataset.leaveDisabled != "true") {
            button.disabled = false;
        }
    }

    button.onclick = function () {
        if (state == 'none') {
            state = 'waiting';
            button.innerHTML = '...';
            button.disabled = true;

            var data = extract_form_data(button.form);
            // We do this here to make sure the form data has the stuff from
            // *our* control. If https://github.com/lemon24/reader/issues/69
            // is implemented by having one form element per control,
            // this won't be needed anymore.
            update_object(data, {action: button.value});

            do_json_request(endpoint, data, function (data) {
                button.innerHTML = 'done';
                callback(data);
                setTimeout(reset_button, DONE_TIMEOUT);
            }, function (message) {
                button.innerHTML = 'error';
                errback(original_text + ': ' + message);
                setTimeout(reset_button, ERROR_TIMEOUT);
            });
        }

        else {
            alert('should not happen');
        }

        return false;
    };
}

function register_confirm(endpoint, collapsible, callback, errback) {
    if (collapsible.dataset.buttonType != 'confirm') { return; }
    var button = collapsible.querySelector('button[name=action]');
    if (button === null) { return; };

    var form = button.form;
    // form.children is a "live collection",
    // weird stuff happens if we mutate while iterating
    var children = Array.from(form.children);
    for (var i = 0; i < children.length; i++) {
        var child = children[i];
        if (child.tagName == 'INPUT' && child.type == 'hidden') {
            continue;
        }
        form.removeChild(child);
    }
    form.appendChild(button);

    var state = 'none';
    var original_text = button.innerHTML;
    var timeout_id = null;

    function reset_button () {
        state = 'none';
        button.innerHTML = original_text;
        if (collapsible.dataset.leaveDisabled != "true") {
            button.disabled = false;
        }
    }

    button.onclick = function () {
        if (state == 'none') {
            state = 'sure';
            button.innerHTML = 'sure?';
            timeout_id = setTimeout(function () {
                state = 'none';
                reset_button();
            }, 2000);
        }

        else if (state == 'sure') {
            state = 'waiting';
            clearTimeout(timeout_id);
            timeout_id = null;
            button.innerHTML = '...';
            button.disabled = true;

            var data = extract_form_data(button.form);
            // We do this here to make sure the form data has the stuff from
            // *our* control. If https://github.com/lemon24/reader/issues/69
            // is implemented by having one form element per control,
            // this won't be needed anymore.
            update_object(data, {action: button.value});

            do_json_request(endpoint, data, function (data) {
                button.innerHTML = 'done';
                callback(data);
                setTimeout(reset_button, DONE_TIMEOUT);
            }, function (message) {
                button.innerHTML = 'error';
                errback(original_text + ': ' + message);
                setTimeout(reset_button, ERROR_TIMEOUT);
            });
        }

        else {
            alert('should not happen');
        }

        return false;
    };
}

function register_text_input(endpoint, collapsible, callback, errback) {
    if (collapsible.dataset.buttonType != 'text-input') { return; }
    var button = collapsible.querySelector('button[name=action]');
    var input = collapsible.querySelector('input[type=text]');
    if (button === null || input === null) { return; };

    var state = 'none';
    var original_text = button.innerHTML;
    var label_text = collapsible.querySelector('.label').innerHTML;

    function reset_button () {
        state = 'none';
        button.innerHTML = original_text;
        if (collapsible.dataset.leaveDisabled != "true") {
            button.disabled = false;
        }
    }

    button.onclick = function () {
        if (state == 'none') {
            state = 'waiting';
            button.innerHTML = '...';
            button.disabled = true;
            if (collapsible.dataset.leaveDisabled == "true") {
                input.disabled = true;
            }

            var data = extract_form_data(button.form);
            // We do this here to make sure the form data has the stuff from
            // *our* control. If https://github.com/lemon24/reader/issues/69
            // is implemented by having one form element per control,
            // this won't be needed anymore.
            update_object(data, {action: button.value});

            do_json_request(endpoint, data, function (data) {
                button.innerHTML = 'done';
                if (collapsible.dataset.leaveDisabled != "true") {
                    input.value = '';
                }
                callback(data);
                setTimeout(reset_button, DONE_TIMEOUT);
            }, function (message) {
                button.innerHTML = 'error';
                input.select();
                errback(label_text + ': ' + message);
                setTimeout(reset_button, ERROR_TIMEOUT);
            });
        }

        else {
            alert('should not happen');
        }

        return false;
    };
}


function register_controls(endpoint, controls) {

    function errback(message) {
        var error = controls.querySelector('.error');

        if (error === null) {
            var template = document.createElement('template');
            template.innerHTML = '<li class="error">';
            controls.appendChild(template.content);
            error = controls.querySelector('.error');
        }

        error.innerHTML = message;
    }

    var collapsible_register_functions = [
        register_simple, register_confirm, register_text_input
    ];

    var collapsibles = controls.querySelectorAll('li');

    for (var ixc = 0; ixc < collapsibles.length; ixc++) {
        var collapsible = collapsibles[ixc];

        if (collapsible.dataset.callback === undefined) {
            continue;
        } else {
            try {
                var callback = eval(collapsible.dataset.callback);
            } catch (e) {
                alert("syntax error in callback: " + collapsible.dataset.callback);
            }
        }

        for (var ixf = 0; ixf < collapsible_register_functions.length; ixf++) {
            collapsible_register_functions[ixf](endpoint, collapsible, callback, errback);
        }
    }

}


function register_all(endpoint) {
    var controls = document.querySelectorAll('.controls');
    for (var ixc = 0; ixc < controls.length; ixc++) {
        var control = controls[ixc];
        register_controls(endpoint, control);
    }
};


function extract_form_data(form) {
    var data = {};
    for (var ix = 0; ix < form.elements.length; ix++) {
        var element = form.elements[ix];
        data[element.name] = element.value;
    }
    return data;
}

function update_object(self, other) {
    for (var attrname in other) { self[attrname] = other[attrname]; }
}

