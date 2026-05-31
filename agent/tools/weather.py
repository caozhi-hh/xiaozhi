"""天气查询工具 — wttr.in"""
import json
import urllib.request
import urllib.parse


def get_weather(city: str) -> str:
    """查询指定城市的当前天气。当用户问天气、温度、是否下雨等问题时使用。"""
    try:
        url = f"https://wttr.in/{urllib.parse.quote(city)}?format=j1"
        req = urllib.request.Request(url, headers={"User-Agent": "curl/7.68.0"})
        resp = urllib.request.urlopen(req, timeout=8)
        data = json.loads(resp.read())
        c = data["current_condition"][0]
        return (
            f"城市: {city}\n"
            f"温度: {c['temp_C']}°C (体感 {c['FeelsLikeC']}°C)\n"
            f"天气: {c['weatherDesc'][0]['value']}\n"
            f"湿度: {c['humidity']}%\n"
            f"风速: {c['windspeedKmph']} km/h"
        )
    except Exception as e:
        return f"查询天气失败: {e}"
