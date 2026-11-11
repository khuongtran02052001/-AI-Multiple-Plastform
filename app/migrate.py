from app.config import settings
from app.db import make_engine, initialize

if __name__ == '__main__':
    settings.validate()
    engine = make_engine(settings.database_url)
    initialize(engine)
    print('Database schema ready. Existing unrelated tables were not modified.')
