import logging

from flask import Flask
from flask import request
from flask_sockets import Sockets
from flask import render_template

app = Flask(__name__)
sockets = Sockets(app)

HTTP_SERVER_PORT = 8080

# Print the payload and return the packet
@app.route('/', methods=['GET', 'POST'])
def echo():
    if request.method == 'POST':
        print(request.data[8:56])
        return request.data #"You send packet {}".format(request.data)
    else:
        return "<p>Hello, World!</p>"

if __name__ == '__main__':
    # Run server
    app.logger.setLevel(logging.INFO)
    from gevent import pywsgi
    from geventwebsocket.handler import WebSocketHandler

    server = pywsgi.WSGIServer(('', HTTP_SERVER_PORT), app, handler_class=WebSocketHandler)
    print("Server listening on: http://localhost:" + str(HTTP_SERVER_PORT))
    try:
        server.serve_forever()
    except KeyboardInterrupt: None