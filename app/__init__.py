from flask import Flask

def create_app():
    app = Flask(__name__)

    from app.routes.health import bp as bp_health
    app.register_blueprint(bp_health)

    @app.route("/")
    def home():
        return {"message": "Flask reset branch running"}, 200

    return app
