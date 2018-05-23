
// TODO: better class names for buttons and controls
// TODO: don't hardcode the li class=error bit
// TODO: no global state


JSON_REQUEST_TIMEOUT = 2000;
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
    var button = collapsible.querySelector('button[value=simple]');
    if (button === null) { return; };

    var state = 'none';
    var original_text = button.innerHTML;

    function reset_button () {
        state = 'none';
        button.innerHTML = original_text;
        button.disabled = false;
    }

    button.onclick = function () {
        if (state == 'none') {
            state = 'waiting';
            button.innerHTML = '...';
            button.disabled = true;
            do_json_request(endpoint, {
                action: button.value,
            }, function (data) {
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
    var button = collapsible.querySelector('button[value=confirm]');
    if (button === null) { return; };

    while (collapsible.firstChild) {
        collapsible.removeChild(collapsible.firstChild);
    }
    collapsible.appendChild(button);

    var state = 'none';
    var original_text = button.innerHTML;
    var timeout_id = null;

    function reset_button () {
        state = 'none';
        button.innerHTML = original_text;
        button.disabled = false;
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
            do_json_request(endpoint, {
                action: button.value,
            }, function (data) {
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

function register_text(endpoint, collapsible, callback, errback) {
    var button = collapsible.querySelector('button[value=text]');
    var input = collapsible.querySelector('input[name=text]');
    if (button === null || input === null) { return; };

    var state = 'none';
    var original_text = button.innerHTML;

    function reset_button () {
        state = 'none';
        button.innerHTML = original_text;
        button.disabled = false;
    }

    button.onclick = function () {
        if (state == 'none') {
            state = 'waiting';
            button.innerHTML = '...';
            button.disabled = true;
            do_json_request(endpoint, {
                action: button.value,
                text: input.value,
            }, function (data) {
                button.innerHTML = 'done';
                input.value = '';
                callback(data);
                setTimeout(reset_button, DONE_TIMEOUT);
            }, function (message) {
                button.innerHTML = 'error';
                input.select();
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
        register_simple, register_confirm, register_text
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

