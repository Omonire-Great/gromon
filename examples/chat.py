"""A tiny WebSocket chat, about forty lines.

    gromon run examples/chat
    then open http://127.0.0.1:8000 in two windows
"""

from gromon import route, run, websocket

PAGE = """<!doctype html>
<title>gromon chat</title>
<style>
body { font: 16px system-ui; max-width: 34rem; margin: 3rem auto; }
#log { border: 1px solid #ccc; height: 18rem; overflow: auto; padding: 8px; }
input, button { font: inherit; padding: 4px; }
</style>
<h1>gromon chat</h1>
<div id="log"></div>
<p><input id="text" size="40" autofocus> <button onclick="send()">send</button></p>
<script>
const socket = new WebSocket("ws://" + location.host + "/ws");
const log = document.getElementById("log");
const show = (line) => {
  log.append(line);
  log.scrollTop = log.scrollHeight;
};
socket.onmessage = (event) => show(event.data);
function send() {
  const box = document.getElementById("text");
  if (box.value) socket.send(box.value), box.value = "";
}
</script>
"""

GUESTS = []


@route("/")
def page():
    return PAGE


@websocket("/ws")
def chat(connection):
    GUESTS.append(connection)
    name = f"guest {len(GUESTS)}"
    try:
        while (message := connection.receive()) is not None:
            for guest in list(GUESTS):
                guest.send_json({"from": name, "text": message})
    finally:
        GUESTS.remove(connection)


if __name__ == "__main__":
    run()
