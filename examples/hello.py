from gromon import route, run


@route("/")
def home():
    return {"message": "Hello World"}


@route("/user/<id>")
def user(id):
    return {"id": int(id)}


@route("/echo", methods=["POST"])
def echo(request):
    return {"you_sent": request.json(), "query": request.query}


if __name__ == "__main__":
    run()
