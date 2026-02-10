from flask import Flask, send_file

app = Flask(__name__, static_folder="data", static_url_path="/data")


@app.route("/")
def index():
    return send_file("ui-sample.html")


if __name__ == "__main__":
    app.run(debug=True, port=5001)
