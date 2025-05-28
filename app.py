import os
import json
import sqlite3
import tornado.ioloop
import tornado.web
import tornado.escape
import requests
from datetime import datetime
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut

# Инициализация базы данных SQLite
def init_db():
    conn = sqlite3.connect('weather_stats.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS city_stats
                 (city TEXT PRIMARY KEY, count INTEGER DEFAULT 0)''')
    conn.commit()
    conn.close()

init_db()

class MainHandler(tornado.web.RequestHandler):
    def get(self):
        # Получаем последний искомый город из cookie
        last_city = self.get_secure_cookie("last_city")
        if last_city:
            last_city = last_city.decode('utf-8')
        self.render("index.html", last_city=last_city)

class WeatherHandler(tornado.web.RequestHandler):
    async def get(self):
        city = self.get_argument("city", None)
        if not city:
            self.write({"error": "Необходимо указать город"})
            return

        try:
            # Получаем координаты города
            geolocator = Nominatim(user_agent="weather_app")
            location = geolocator.geocode(city)
            
            if location is None:
                self.write({"error": "Город не найден"})
                return

            try:
                # Обновляем статистику поиска в базе данных
                conn = sqlite3.connect('weather_stats.db')
                c = conn.cursor()
                c.execute('''INSERT INTO city_stats (city, count) 
                           VALUES (?, 1) 
                           ON CONFLICT(city) 
                           DO UPDATE SET count = count + 1''', (city.lower(),))
                conn.commit()
                conn.close()
            except Exception as e:
                print(f"Ошибка базы данных: {e}")

            # Сохраняем последний искомый город в cookie
            self.set_secure_cookie("last_city", city)

            # Получаем данные о погоде из API Open-Meteo
            weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={location.latitude}&longitude={location.longitude}&hourly=temperature_2m,precipitation_probability,weathercode&timezone=auto"
            response = requests.get(weather_url)
            weather_data = response.json()

            # Обрабатываем и форматируем данные о погоде
            formatted_data = self.format_weather_data(weather_data)
            self.write(formatted_data)

        except Exception as e:
            self.write({"error": str(e)})

    def format_weather_data(self, data):
        hourly_data = []
        for i in range(24):  # Следующие 24 часа
            weather_code = data["hourly"]["weathercode"][i]
            weather_description = self.get_weather_description(weather_code)
            
            hourly_data.append({
                "time": data["hourly"]["time"][i],
                "temperature": data["hourly"]["temperature_2m"][i],
                "precipitation_probability": data["hourly"]["precipitation_probability"][i],
                "weather_description": weather_description
            })
        
        return {"forecast": hourly_data}

    def get_weather_description(self, code):
        weather_codes = {
            0: "Ясно",
            1: "Преимущественно ясно",
            2: "Переменная облачность",
            3: "Пасмурно",
            45: "Туман",
            48: "Изморозь",
            51: "Легкая морось",
            53: "Умеренная морось",
            55: "Сильная морось",
            61: "Небольшой дождь",
            63: "Умеренный дождь",
            65: "Сильный дождь",
            71: "Небольшой снег",
            73: "Умеренный снег",
            75: "Сильный снег",
            95: "Гроза"
        }
        return weather_codes.get(code, "Неизвестно")

class CitySuggestHandler(tornado.web.RequestHandler):
    async def get(self):
        query = self.get_argument("q", "").lower()
        if len(query) < 2:
            self.write({"suggestions": []})
            return

        try:
            # Получаем города из базы данных, соответствующие запросу
            conn = sqlite3.connect('weather_stats.db')
            c = conn.cursor()
            c.execute('''SELECT city FROM city_stats 
                        WHERE city LIKE ? 
                        ORDER BY count DESC''', (f'%{query}%',))
            matching_cities = [row[0] for row in c.fetchall()]
            conn.close()
        except Exception as e:
            print(f"Ошибка базы данных при поиске подсказок: {e}")
            matching_cities = []

        # Если недостаточно совпадений из истории, добавляем популярные города
        if len(matching_cities) < 5:
            common_cities = ["Москва", "Санкт-Петербург", "Новосибирск", "Екатеринбург", "Казань"]
            for city in common_cities:
                if query in city.lower() and city not in matching_cities:
                    matching_cities.append(city)

        self.write({"suggestions": matching_cities[:5]})

class StatsHandler(tornado.web.RequestHandler):
    async def get(self):
        try:
            # Получаем топ-10 искомых городов с их счетчиками
            conn = sqlite3.connect('weather_stats.db')
            c = conn.cursor()
            c.execute('''SELECT city, count FROM city_stats 
                        ORDER BY count DESC LIMIT 10''')
            stats = [{"city": city, "count": count} 
                    for city, count in c.fetchall()]
            conn.close()
        except Exception as e:
            print(f"Ошибка базы данных при получении статистики: {e}")
            stats = []
        
        self.write({"stats": stats})

def make_app():
    return tornado.web.Application([
        (r"/", MainHandler),
        (r"/weather", WeatherHandler),
        (r"/suggest", CitySuggestHandler),
        (r"/stats", StatsHandler),
        (r"/static/(.*)", tornado.web.StaticFileHandler, {"path": "static"}),
    ],
    template_path="templates",
    static_path="static",
    cookie_secret="5206677180a9431e80a7e301367034c8"  # Постоянный секретный ключ для подписи cookies
    )

if __name__ == "__main__":
    app = make_app()
    app.listen(8888)
    print("Сервер запущен по адресу http://localhost:8888")
    tornado.ioloop.IOLoop.current().start() 