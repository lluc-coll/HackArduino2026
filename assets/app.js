// SPDX-FileCopyrightText: Copyright (C) ARDUINO SRL (http://www.arduino.cc)
//
// SPDX-License-Identifier: MPL-2.0

const MAX_EVENTS = 20;
const socket = io(`http://${window.location.host}`);
const events = [];

const errorContainer = document.getElementById('error-container');
const scoreValue = document.getElementById('scoreValue');
const timeValue = document.getElementById('timeValue');
const statusPill = document.getElementById('statusPill');
const eventList = document.getElementById('eventList');

const sensitivitySlider = document.getElementById('sensitivitySlider');
const sensitivityInput = document.getElementById('sensitivityInput');
const alarmSlider = document.getElementById('alarmSlider');
const alarmInput = document.getElementById('alarmInput');
const delaySlider = document.getElementById('delaySlider');
const delayInput = document.getElementById('delayInput');
const rebaselineButton = document.getElementById('rebaselineButton');

const frameImage = document.getElementById('frameImage');
const placeholder = document.getElementById('videoPlaceholder');

document.addEventListener('DOMContentLoaded', () => {
    initSocket();
    initControls();
    renderEvents();
});

function initSocket() {
    socket.on('connect', () => {
        if (errorContainer) {
            errorContainer.style.display = 'none';
            errorContainer.textContent = '';
        }
        socket.emit('get_status', true);
    });

    socket.on('disconnect', () => {
        if (errorContainer) {
            errorContainer.textContent = 'Connection to the board lost. Please check the connection.';
            errorContainer.style.display = 'block';
        }
    });

    socket.on('monitor_status', (message) => {
        if (!message) return;
        const isError = message.status === 'error';
        setStatus(isError ? 'ERROR' : 'RUNNING', isError);

        if (isError && errorContainer) {
            errorContainer.textContent = message.message || 'Monitor error';
            errorContainer.style.display = 'block';
        }

        if (message.config) {
            applyConfigToControls(message.config);
        }
        if (message.message) {
            addEvent({
                title: message.message,
                subtitle: `Status: ${message.status || 'unknown'}`,
            });
        }
    });

    socket.on('pollen_update', (message) => {
        if (!message) return;
        scoreValue.textContent = String(message.score);
        timeValue.textContent = message.timestamp || '--:--:--';

        if (message.frame) {
            frameImage.src = message.frame;
            frameImage.style.display = 'block';
            placeholder.style.display = 'none';
        }

        if (message.isAlert) {
            setStatus('ALERT', true);
        } else {
            setStatus('RUNNING', false);
        }

        if (message.config) {
            applyConfigToControls(message.config);
        }

        addEvent({
            title: `Score ${message.score}${message.isAlert ? ' - ALERT' : ''}`,
            subtitle: `Updated at ${message.timestamp}`,
        });
    });
}

function setStatus(text, isAlert) {
    statusPill.textContent = text;
    statusPill.classList.toggle('alert', Boolean(isAlert));
}

function addEvent(event) {
    events.unshift(event);
    if (events.length > MAX_EVENTS) {
        events.pop();
    }
    renderEvents();
}

function renderEvents() {
    eventList.innerHTML = '';
    if (events.length === 0) {
        const li = document.createElement('li');
        li.className = 'event-item';
        li.innerHTML = '<div class="event-subtitle">No readings yet. Waiting for first test sample...</div>';
        eventList.appendChild(li);
        return;
    }

    events.forEach((event) => {
        const li = document.createElement('li');
        li.className = 'event-item';
        li.innerHTML = `
            <div class="event-title">${event.title}</div>
            <div class="event-subtitle">${event.subtitle}</div>
        `;
        eventList.appendChild(li);
    });
}

function initControls() {
    bindPair(sensitivitySlider, sensitivityInput, (v) => socket.emit('set_sensitivity', parseInt(v, 10)));
    bindPair(alarmSlider, alarmInput, (v) => socket.emit('set_alarm_threshold', parseInt(v, 10)));
    bindPair(delaySlider, delayInput, (v) => socket.emit('set_test_delay', parseFloat(v)));

    rebaselineButton.addEventListener('click', () => {
        socket.emit('rebaseline', true);
        addEvent({
            title: 'New baseline requested',
            subtitle: 'Waiting for camera capture...',
        });
    });
}

function bindPair(slider, numberInput, onValueChange) {
    slider.addEventListener('input', () => {
        numberInput.value = slider.value;
        onValueChange(slider.value);
    });

    numberInput.addEventListener('change', () => {
        const min = Number(numberInput.min);
        const max = Number(numberInput.max);
        let value = Number(numberInput.value);
        if (Number.isNaN(value)) {
            value = Number(slider.value);
        }
        value = Math.max(min, Math.min(max, value));
        numberInput.value = String(value);
        slider.value = String(value);
        onValueChange(value);
    });
}

function applyConfigToControls(config) {
    if (typeof config.sensitivity !== 'undefined') {
        sensitivitySlider.value = String(config.sensitivity);
        sensitivityInput.value = String(config.sensitivity);
    }

    if (typeof config.alarm_threshold !== 'undefined') {
        alarmSlider.value = String(config.alarm_threshold);
        alarmInput.value = String(config.alarm_threshold);
    }

    if (typeof config.test_delay !== 'undefined') {
        delaySlider.value = String(config.test_delay);
        delayInput.value = String(config.test_delay);
    }
}
