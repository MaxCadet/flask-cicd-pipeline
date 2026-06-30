from flask import Flask, jsonify

app = Flask(__name__)

@app.route("/")
def home():
    return jsonify({
        "message": "Flask CI/CD Pipeline",
        "status": "healthy",
        "version": "1.1.0"
    })

@app.route("/health")
def health():
    return jsonify({"status": "healthy"}), 200

app.run(host="0.0.0.0", port=5000)