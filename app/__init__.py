from flask import Flask

def create_app():
    app = Flask(__name__)

    # 기존
    from app.routes.health import bp as bp_health
    app.register_blueprint(bp_health)

    # ✅ 추가: generate 라우트 등록
    from app.routes.route_generate import bp as bp_generate
    app.register_blueprint(bp_generate)

    return app
