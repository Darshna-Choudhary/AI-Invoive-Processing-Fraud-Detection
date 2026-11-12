from flask import Flask
from routes.extraction_routes import extraction_bp


def create_app():
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024
    app.register_blueprint(extraction_bp, url_prefix="/api")
    return app


app = create_app()

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )