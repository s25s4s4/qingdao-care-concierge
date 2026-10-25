import urllib.request
import json
import sqlite3
import math
import os
import re
from datetime import datetime

# 网关密钥从环境变量读取，不再硬编码（该文件曾把明文 key 推进了公开仓库，
# 2026-10-22 修复）。本地网关密钥如有泄露疑虑，请在 aiclient2api 侧重生成一个。
LLM_URL = os.environ.get("LLM_URL", "http://127.0.0.1:3000/gemini-antigravity/v1/chat/completions")
LLM_KEY = os.environ.get("LLM_KEY", "")
DB_PATH = r"E:\telegram_football_monitor\predictions.db"

# 欧洲主流多语言队名别名对照
ALIAS_MAP = {
    "法兰克福": [
                "frankfurt",
                "eintracht",
                "франкфурт",
                "آينتراخت",
                "francfort"
    ],
    "科隆": [
                "cologne",
                "koln",
                "köln",
                "кельн",
                "كولن"
    ],
    "纽伦堡": [
                "nurnberg",
                "nürnberg",
                "нюрнберг",
                "نورنبرغ"
    ],
    "科特布斯": [
                "cottbus",
                "котбус",
                "كوتبوس"
    ],
    "拜仁": [
                "bayern",
                "munich",
                "бавария",
                "بايرن",
                "múnich",
                "baviera"
    ],
    "莱红牛": [
                "leipzig",
                "rb leipzig",
                "лейпциг",
                "لايبزيغ"
    ],
    "多特蒙德": [
                "dortmund",
                "bvb",
                "дортмунд",
                "دورتموند"
    ],
    "柏林联合": [
                "union berlin",
                "унион берлин",
                "يونيون برلين"
    ],
    "不来梅": [
                "bremen",
                "werder",
                "бремен",
                "بريمن"
    ],
    "斯图加特": [
                "stuttgart",
                "штутгарт",
                "شتوتغارت"
    ],
    "汉堡": [
                "hsv",
                "hamburg",
                "гамбург",
                "هامبورغ"
    ],
    "沙尔克": [
                "schalke",
                "шальке",
                "شالكه"
    ],
    "美因茨": [
                "mainz",
                "майнц",
                "ماينتس"
    ],
    "奥格斯堡": [
                "augsburg",
                "аугсбург",
                "أوغسبورغ"
    ],
    "曼联": [
                "man utd",
                "manchester united",
                "mufc",
                "манчестер юнайтед",
                "مانشستر يونايتد"
    ],
    "利兹联": [
                "leeds",
                "лидс",
                "ليدز يونايتد"
    ],
    "阿森纳": [
                "arsenal",
                "gunners",
                "арсенал",
                "أرسنال"
    ],
    "诺丁汉": [
                "forest",
                "nottingham",
                "ноттингем",
                "نوتنغهام"
    ],
    "切尔西": [
                "chelsea",
                "cfc",
                "челси",
                "تشيلسي"
    ],
    "埃弗顿": [
                "everton",
                "эвертон",
                "إيفرتون"
    ],
    "曼城": [
                "man city",
                "mcfc",
                "манчестер сити",
                "مانشستر سيتي"
    ],
    "伊普斯": [
                "ipswich",
                "ипсвич",
                "إبسويتش"
    ],
    "纽卡斯尔": [
                "newcastle",
                "ньюкасл",
                "نيوكاسل"
    ],
    "维拉": [
                "aston villa",
                "villa",
                "астон вилла",
                "أستون فيلا"
    ],
    "利物浦": [
                "liverpool",
                "ливерпуль",
                "ليفربول"
    ],
    "布伦特": [
                "brentford",
                "брентфорд",
                "برينتفورد"
    ],
    "富勒姆": [
                "fulham",
                "фулхэм",
                "فولهام"
    ],
    "伯恩利": [
                "burnley",
                "бернли",
                "بيرنلي"
    ],
    "伍尔弗汉普顿": [
                "wolves",
                "wolverhampton",
                "вулверхэмптон",
                "ولفرهامبتون"
    ],
    "弗洛西诺": [
                "frosinone",
                "фрозиноне",
                "فروزينوني"
    ],
    "萨索洛": [
                "sassuolo",
                "сассуоло",
                "ساسولو"
    ],
    "国际米兰": [
                "inter",
                "internazionale",
                "интер",
                "إنتر ميلان"
    ],
    "博洛尼亚": [
                "bologna",
                "болонья",
                "بولونيا"
    ],
    "那不勒斯": [
                "napoli",
                "наполи",
                "نابولي"
    ],
    "威尼斯": [
                "venezia",
                "венеция",
                "فينيزيا"
    ],
    "罗马": [
                "roma",
                "рим",
                "روما"
    ],
    "热那亚": [
                "genoa",
                "дsubjenoa",
                "генуя",
                "جنوى"
    ],
    "乌迪内斯": [
                "udinese",
                "удинезе",
                "أودينيزي"
    ],
    "莱切": [
                "lecce",
                "лечче",
                "ليتشي"
    ],
    "佛罗伦萨": [
                "fiorentina",
                "фиорентина",
                "فيورنتينا"
    ],
    "科莫": [
                "como",
                "комо",
                "كومو"
    ],
    "巴萨": [
                "barca",
                "barcelona",
                "барселона",
                "برشلونة",
                "fcb"
    ],
    "贝蒂斯": [
                "betis",
                "бетис",
                "بيتيس"
    ],
    "马竞": [
                "atletico",
                "atlético",
                "атлетико",
                "أتلتيكو"
    ],
    "西班牙人": [
                "espanyol",
                "эспаньол",
                "إسبانيول"
    ],
    "比利亚雷亚尔": [
                "villarreal",
                "вильярреал",
                "فياريال"
    ],
    "巴伦西亚": [
                "valencia",
                "валенсия",
                "فالنسيا"
    ],
    "毕尔巴鄂": [
                "bilbao",
                "athletic",
                "бильбао",
                "بيلباو"
    ],
    "奥萨苏纳": [
                "osasuna",
                "осасуна",
                "أوساسونا"
    ],
    "桑坦德": [
                "santander",
                "сантандер",
                "راسينغ"
    ],
    "拉科": [
                "deportivo",
                "coruna",
                "депортиво",
                "ديبورتيفو"
    ],
    "莱万特": [
                "levante",
                "леванте",
                "ليفانتي"
    ],
    "巴黎": [
                "psg",
                "paris",
                "париж",
                "باريس سان جيرمان"
    ],
    "斯特拉斯": [
                "strasbourg",
                "страсбур",
                "ستراسبورغ"
    ],
    "图卢兹": [
                "toulouse",
                "тулуза",
                "تولوز"
    ],
    "勒芒": [
                "le mans",
                "ле-ман",
                "لومان"
    ],
    "费耶诺德": [
                "feyenoord",
                "фейеноорд",
                "فاينورد"
    ],
    "阿贾克斯": [
                "ajax",
                "аякс",
                "أياكس"
    ],
    "海伦芬": [
                "heerenveen",
                "херенвен",
                "هيرينفين"
    ],
    "登博思": [
                "den bosch",
                "ден бош",
                "دين بوش"
    ],
    "奥斯": [
                "oss",
                "топ осс",
                "أوس"
    ],
    "悉尼FC": [
                "sydney",
                "сидней",
                "سيدني"
    ],
    "西悉尼": [
                "western sydney",
                "wanderers",
                "уэстерн сидней",
                "ويسترن سيدني"
    ],
    "麦克阿瑟": [
                "macarthur",
                "макартур",
                "ماكارثر"
    ],
    "珀斯": [
                "perth",
                "перт глори",
                "بيرث"
    ],
    "鹿岛": [
                "kashima",
                "касима",
                "كاشيما"
    ],
    "蔚山": [
                "ulsan",
                "ульсан",
                "أولسان"
    ],
    "首尔FC": [
                "seoul",
                "сеул",
                "سيول"
    ],
    "米拉索尔": [
                "mirassol",
                "мирасол",
                "ميراسول"
    ],
    "巴西国际": [
                "internacional",
                "интернасьонал",
                "إنترناسيونال"
    ],
    "仙台七夕": ["sapporo", "consadole"],
    "兰斯": ["lens", "rc lens"],
    "冈山绿雉": ["okayama", "fagiano"],
    "哥德堡": ["göteborg", "gais", "ifk göteborg"],
    "圣克拉拉": ["santa clara"],
    "布洛涅": ["boulogne"],
    "新潟天鹅": ["niigata", "albirex"],
    "本菲卡": ["benfica"],
    "水户蜀葵": ["mito", "hollyhock"],
    "洛城银河": ["la galaxy", "galaxy", "lag"],
    "洛杉矶FC": ["lafc", "la fc"],
    "济州SK": ["jeju", "jeju united"],
    "特温特": ["twente"],
    "特罗姆瑟": ["tromsø", "tromso"],
    "盖斯": ["gais"],
    "福图纳": ["fortuna sittard", "fortuna"],
    "米竞技": ["atletico mineiro", "atletico-mg"],
    "维塞乌": ["farense"],
    "阿尔克马": ["az alkmaar", "az"],
    "阿德莱德": ["adelaide", "adelaide united"]
    "AC米兰": [
                "['AC Milan']",
    ],
    "SBV精英": [
                "['Excelsior']",
    ],
    "中央海岸": [
                "['Central Coast Mariners']",
    ],
    "亚特兰大": [
                "['Atalanta']",
    ],
    "仁川联": [
                "['Incheon United']",
    ],
    "代格福什": [
                "['Degerfors']",
    ],
    "伯恩茅斯": [
                "['Bournemouth']",
    ],
    "佐加顿斯": [
                "['Djurgården']",
    ],
    "兹沃勒": [
                "['PEC Zwolle']",
    ],
    "前进之鹰": [
                "['Go Ahead Eagles']",
    ],
    "勒沃库森": [
                "['Bayer Leverkusen']",
    ],
    "博德闪耀": [
                "['Bodø/Glimt']",
    ],
    "卡利亚里": [
                "['Cagliari']",
    ],
    "卡尔马": [
                "['Kalmar FF']",
    ],
    "吉维森特": [
                "['Gil Vicente']",
    ],
    "名古屋鲸": [
                "['Nagoya Grampus']",
    ],
    "埃夫斯堡": [
                "['Elfsborg']",
    ],
    "埃尔切": [
                "['Elche']",
    ],
    "埃沃斯堡": [
                "['Elversberg']",
    ],
    "塞尔塔": [
                "['Celta Vigo']",
    ],
    "塞维利亚": [
                "['Sevilla']",
    ],
    "天狼星": [
                "['IK Sirius']",
    ],
    "宫崎惊奇牛鸟": [
                "['Tegevajaro Miyazaki']",
    ],
    "富川FC": [
                "['Bucheon FC 1995']",
    ],
    "尤文图斯": [
                "['Juventus']",
    ],
    "尼斯": [
                "['Nice']",
    ],
    "巴列卡诺": [
                "['Rayo Vallecano']",
    ],
    "巴黎圣曼": [
                "['Paris Saint-Germain']",
    ],
    "布拉加": [
                "['Braga']",
    ],
    "布鲁马波": [
                "['Brommapojkarna']",
    ],
    "帕尔马": [
                "['Parma']",
    ],
    "帕德博恩": [
                "['Paderborn']",
    ],
    "库奥皮奥": [
                "['Kuopion Palloseura']",
    ],
    "弗赖堡": [
                "['Freiburg']",
    ],
    "弗鲁米嫩": [
                "['Fluminense']",
    ],
    "拉齐奥": [
                "['Lazio']",
    ],
    "摩纳哥": [
                "['Monaco']",
    ],
    "新英格兰": [
                "['New England Revolution']",
    ],
    "昂热": [
                "['Angers']",
    ],
    "林肯城": [
                "['Lincoln City']",
    ],
    "柏太阳神": [
                "['Kashiwa Reysol']",
    ],
    "格罗宁根": [
                "['Groningen']",
    ],
    "桑德兰": [
                "['Sunderland']",
    ],
    "桑托斯": [
                "['Santos']",
    ],
    "比利亚雷": [
                "['Villarreal']",
    ],
    "汉坎": [
                "['HamKam']",
    ],
    "江原FC": [
                "['Gangwon FC']",
    ],
    "沙尔克04": [
                "['Schalke 04']",
    ],
    "洛里昂": [
                "['Lorient']",
    ],
    "热刺": [
                "['Tottenham Hotspur']",
    ],
    "特尔斯达": [
                "['Telstar']",
    ],
    "瓦萨": [
                "['VPS']",
    ],
    "町田泽维": [
                "['Machida Zelvia']",
    ],
    "皇家社会": [
                "['Real Sociedad']",
    ],
    "皇马": [
                "['Real Madrid']",
    ],
    "磐田喜悦": [
                "['Jubilo Iwata']",
    ],
    "福冈黄蜂": [
                "['Avispa Fukuoka']",
    ],
    "科林蒂安": [
                "['Corinthians']",
    ],
    "米尔沃尔": [
                "['Millwall']",
    ],
    "纽喷气机": [
                "['Newcastle Jets']",
    ],
    "维多利亚": [
                "['Victoria']",
    ],
    "罗德兹": [
                "['Rodez AF']",
    ],
    "罗森博格": [
                "['Rosenborg']",
    ],
    "考文垂": [
                "['Coventry City']",
    ],
    "芝加哥": [
                "['Chicago Fire']",
    ],
    "萨普斯堡": [
                "['Sarpsborg 08']",
    ],
    "蒙彼利埃": [
                "['Montpellier']",
    ],
    "蒙扎": [
                "['Monza']",
    ],
    "蔚山现代": [
                "['Ulsan HD']",
    ],
    "赫塔费": [
                "['Getafe']",
    ],
    "赫尔城": [
                "['Hull City']",
    ],
    "赫尔辛基": [
                "['Helsingin Jalkapalloklubi']",
    ],
    "赫尔辛基火花": [
                "['HJK Klubi 04']",
    ],
    "都灵": [
                "['Torino']",
    ],
    "里昂": [
                "['Lyon']",
    ],
    "金泉尚武": [
                "['Gimcheon Sangmu']",
    ],
    "长崎航海": [
                "['V-Varen Nagasaki']",
    ],
    "门兴": [
                "['Borussia Monchengladbach']",
    ],
    "阿拉维斯": [
                "['Alaves']",
    ],
    "霍芬海姆": [
                "['Hoffenheim']",
    ],
    "马拉加": [
                "['Málaga']",
    ],
    "马赛": [
                "['Marseille']",
    ],
    "鹿岛鹿角": [
                "['Kashima Antlers']",
    ],
    "麦克阿瑟FC": [
                "['Macarthur FC']",
    ],
    "布莱顿": [
                "['Brighton & Hove Albion']",
    ],
    "水晶宫": [
                "['Crystal Palace']",
    ],
    "里尔": [
                "['Lille']",
    ],
    "雷恩": [
                "['Rennes']",
    ],
    "朗斯": [
                "['Lens']",
    ],
    "布雷斯特": [
                "['Brest']",
    ],
    "欧塞尔": [
                "['Auxerre']",
    ],
    "特鲁瓦": [
                "['Troyes']",
    ],
    "勒阿弗尔": [
                "['Le Havre AC']",
    ],
    "LASK林茨": [
                "['LASK']",
    ],
    "东京FC": [
                "['FC Tokyo']",
    ],
    "克里特": [
                "['OFI Crete']",
    ],
    "凯尔特人": [
                "['Celtic']",
    ],
    "利勒斯特": [
                "['Lillestrøm']",
    ],
    "加拉塔萨": [
                "['Galatasaray']",
    ],
    "博尔顿": [
                "['Bolton Wanderers']",
    ],
    "吉马良斯": [
                "['Vitória Guimarães']",
    ],
    "埃因霍温": [
                "['PSV Eindhoven']",
    ],
    "大宫松鼠RB": [
                "['Omiya Ardija']",
    ],
    "奈梅亨": [
                "['NEC Nijmegen']",
    ],
    "富山胜利": [
                "['Kataller Toyama']",
    ],
    "川崎前锋": [
                "['Kawasaki Frontale']",
    ],
    "布拉迪斯": [
                "['Slovan Bratislava']",
    ],
    "布里斯班": [
                "['Brisbane Roar']",
    ],
    "布雷达": [
                "['NAC Breda']",
    ],
    "布鲁日": [
                "['Club Brugge']",
    ],
    "帕梅拉斯": [
                "['Palmeiras']",
    ],
    "弗拉门戈": [
                "['Flamengo']",
    ],
    "拉普大学": [
                "['Estudiantes']",
    ],
    "斯拉维亚": [
                "['Slavia Prague']",
    ],
    "朴次茅斯": [
                "['Portsmouth']",
    ],
    "格风暴": [
                "['Sturm Graz']",
    ],
    "沃夫斯堡": [
                "['Wolfsburg']",
    ],
    "波兹南": [
                "['Lech Poznań']",
    ],
    "波尔图": [
                "['FC Porto']",
    ],
    "波鸿": [
                "['Bochum']",
    ],
    "神户胜利": [
                "['Vissel Kobe']",
    ],
    "米堡": [
                "['Middlesbrough']",
    ],
    "维京": [
                "['Viking']",
    ],
    "萨巴赫": [
                "['Sabah FK']",
    ],
    "萨迪纳摩": [
                "['Dinamo Zagreb']",
    ],
    "贝西克塔": [
                "['Beşiktaş']",
    ],
    "费内巴切": [
                "['Fenerbahçe']",
    ],
    "赫拉克勒": [
                "['Heracles']",
    ],
    "里斯本": [
                "['Sporting CP']",
    ],
    "雅典AEK": [
                "['AEK Athens']",
    ],
    "马尔默": [
                "['Malmö FF']",
    ],
    "马里迪莫": [
                "['Marítimo']",
    ],
    "墨胜利": [
                "['Melbourne Victory']",
    ],
    "墨尔本城": [
                "['Melbourne City']",
    ],
    "查尔顿": [
                "['Charlton Athletic']",
    ],
    "诺维奇": [
                "['Norwich City']",
    ],
    "瓦勒伦加": [
                "['Vålerenga']",
    ],
    "乌德勒支": [
                "['FC Utrecht']",
    ],
    "阿马多拉": [
                "['Estrela da Amadora']",
    ],
    "卡萨皮亚": [
                "['Casa Pia']",
    ],
    "巴黎FC": [
                "['Paris FC']",
    ],
    "巴伊亚": [
                "['Bahia']",
    ],
    "莱斯特": [
                "['Leicester City']",
    ],
    "狼队": [
                "['Wolverhampton Wanderers']",
    ],
    "西汉姆": [
                "['West Ham United']",
    ],
    "瓦伦西亚": [
                "['Valencia']",
    ],
    "皇社": [
                "['Real Sociedad']",
    ],
    "赫罗纳": [
                "['Girona']",
    ],
    "加的斯": [
                "['Cadiz']",
    ],
    "马洛卡": [
                "['Mallorca']",
    ],
    "拉斯帕尔马斯": [
                "['Las Palmas']",
    ],
    "萨拉戈萨": [
                "['Zaragoza']",
    ],
    "国米": [
                "['Inter Milan']",
    ],
    "维罗纳": [
                "['Hellas Verona']",
    ],
    "恩波利": [
                "['Empoli']",
    ],
    "沃尔夫斯堡": [
                "['Wolfsburg']",
    ],
    "布伦瑞克": [
                "['Eintracht Braunschweig']",
    ],
    "达姆施塔特": [
                "['Darmstadt 98']",
    ],
    "南特": [
                "['FC Nantes']",
    ],
    "克莱蒙": [
                "['Clermont Foot']",
    ],
    "广岛三箭": [
                "['Sanfrecge Hiroshima']",
    ],
    "浦和红钻": [
                "['Urawa Red Diamonds']",
    ],
    "大阪钢巴": [
                "['Gamba Osaka']",
    ],
    "札幌冈萨多": [
                "['Consadole Sapporo']",
    ],
    "新泻天鹅": [
                "['Albirex Niigata']",
    ],
    "鸟栖砂岩": [
                "['Sagan Tosu']",
    ],
    "琉球FC": [
                "['Llivia FC']",
    ],
    "清水鼓动": [
                "['Shimizu S-Pulse']",
    ],
    "横滨水手": [
                "['Yokohama F. Marinos']",
    ],
    "千叶市原": [
                "['Kashiwa Reysol']",
    ],
    "山形山神": [
                "['Montedio Yamagata']",
    ],
    "爱媛FC": [
                "['Ehime FC']",
    ],
    "大分三神": [
                "['Oita Trinita']",
    ],
    "山口雷法": [
                "['Renofa Yamaguchi']",
    ],
    "金泽撒维根": [
                "['Kagoshima United']",
    ],
    "德岛漩涡": [
                "['Tokushima Vortis']",
    ],
    "岩手盛冈仙鹤": [
                "['Iwate Grulla Morioka']",
    ],
    "滋贺琵琶湖": [
                "['Lake Biwa Shiga']",
    ],
    "福冈黄蜂B": [
                "['Avispa Fukuoka II']",
    ],
    "岐阜FC": [
                "['Gifu FC']",
    ],
    "松本山雅": [
                "['Matsumoto Yamaga']",
    ],
    "秋田蓝色闪电": [
                "['Blaublitz Akita']",
    ],
    "全北现代": [
                "['Jeonbuk Hyundai']",
    ],
    "浦项制铁": [
                "['Pohang Steelers']",
    ],
    "大田市民": [
                "['Daejeon Hana Citizen']",
    ],
    "光州FC": [
                "['Gwangju FC']",
    ],
    "城南FC": [
                "['Seongnam FC']",
    ],
    "大邱FC": [
                "['Daegu FC']",
    ],
    "惠灵顿凤凰": [
                "['Wellington Phoenix']",
    ],
    "上海海港": [
                "['Shanghai Port']",
    ],
    "上海申花": [
                "['Shanghai Shenhua']",
    ],
    "山东泰山": [
                "['Shandong Taishan']",
    ],
    "北京国安": [
                "['Beijing Guoan']",
    ],
    "广州恒大": [
                "['Guangzhou FC']",
    ],
    "武汉三镇": [
                "['Wuhan Three Towns']",
    ],
    "成都蓉城": [
                "['Chengdu Rongcheng']",
    ],
    "浙江队": [
                "['Zhejiang FC']",
    ],
    "长春亚泰": [
                "['Changchun Yatai']",
    ],
    "河南队": [
                "['Henan FC']",
    ],
    "天津津门虎": [
                "['Tianjin Jinmen Tiger']",
    ],
    "重庆两江竞技": [
                "['Chongqing Liangjiang Athletic']",
    ],
    "深圳队": [
                "['Shenzhen FC']",
    ],
    "沧州雄狮": [
                "['Cangzhou Mighty Lions']",
    ],
    "河北队": [
                "['Hebei FC']",
    ],
    "大连人": [
                "['Dalian Pro']",
    ],
    "帕尔梅拉斯": [
                "['Palmeiras']",
    ],
    "圣保罗": [
                "['São Paulo FC']",
    ],
    "格雷米奥": [
                "['Gremio']",
    ],
    "邦迪比斯塔": [
                "['Botafogo']",
    ],
    "巴拉纳": [
                "['Coritiba']",
    ],
    "克里西UMA": [
                "['Criciuma']",
    ],
    "累西腓体育": [
                "['Sport Recife']",
    ],
    "戈亚斯": [
                "['Goias']",
    ],
    "阿戈里亚": [
                "['Athletico Paranaense']",
    ],
    "科里蒂巴": [
                "['Coritiba']",
    ],
    "塞阿拉": [
                "['Ceara']",
    ],
    "福塔雷萨": [
                "['Fortaleza']",
    ],
    "布拉甘蒂诺": [
                "['Red Bull Bragantino']",
    ],
    "河床": [
                "['River Plate']",
    ],
    "博卡青年": [
                "['Boca Juniors']",
    ],
    "独立队": [
                "['Independiente']",
    ],
    "国民竞技": [
                "['Atletico Nacional']",
    ],
    "米内罗竞技": [
                "['America Mineiro']",
    ],
    "阿根廷青年人": [
                "['Argentinos Juniors']",
    ],
    "青年竞技": [
                "['Almagro']",
    ],
    "塔勒瑞斯": [
                "['Talleres']",
    ],
    "拉努斯": [
                "['Lanus']",
    ],
    "竞技俱乐部": [
                "['Atletico Tucuman']",
    ],
    "防卫者": [
                "['Defensa y Justicia']",
    ],
    "萨斯菲尔德": [
                "['Velez Sarsfield']",
    ],
    "基多体育": [
                "['LDU Quito']",
    ],
    "巴塞罗那SC": [
                "['Barcelona SC']",
    ],
    "卡拉卡斯": [
                "['Caracas FC']",
    ],
    "纽约城": [
                "['NYCFC']",
    ],
    "纽约红牛": [
                "['NY Red Bulls']",
    ],
    "费城联": [
                "['Philadelphia Union']",
    ],
    "亚特兰大联": [
                "['Atlanta United']",
    ],
    "迈阿密国际": [
                "['Inter Miami']",
    ],
    "多伦多FC": [
                "['Toronto FC']",
    ],
    "蒙特利尔冲击": [
                "['CF Montreal']",
    ],
    "哥伦布机员": [
                "['Columbus Crew']",
    ],
    "新英格兰革命": [
                "['New England Revolution']",
    ],
    "芝加哥火焰": [
                "['Chicago Fire']",
    ],
    "纽约宇宙": [
                "['New York Cosmos']",
    ],
    "休斯顿迪纳摩": [
                "['Houston Dynamo']",
    ],
    "达拉斯FC": [
                "['FC Dallas']",
    ],
    "圣何塞地震": [
                "['San Jose Earthquakes']",
    ],
    "西雅图海湾人": [
                "['Seattle Sounders']",
    ],
    "波特兰伐木工": [
                "['Portland Timbers']",
    ],
    "皇家盐湖城": [
                "['Real Salt Lake']",
    ],
    "科罗拉多急流": [
                "['Colorado Rapids']",
    ],
    "明尼苏达联": [
                "['Minnesota United']",
    ],
    "纳什维尔SC": [
                "['Nashville SC']",
    ],
    "堪萨斯城竞技": [
                "['Sporting KC']",
    ],
    "辛辛那提FC": [
                "['FC Cincinnati']",
    ],
    "华盛顿联": [
                "['DC United']",
    ],
    "温哥华白帽": [
                "['Vancouver Whitecaps']",
    ],
    "PSV埃因霍温": [
                "['PSV Eindhoven']",
    ],
    "坎布尔": [
                "['Cambuur']",
    ],
    "瓦尔韦克": [
                "['Willem II']",
    ],
    "埃因霍温青年队": [
                "['PSV Youth']",
    ],
    "威廉二世": [
                "['Willem II']",
    ],
    "罗达JC": [
                "['Rodajc']",
    ],
    "阿尔梅勒城": [
                "['Almere City']",
    ],
    "埃门": [
                "['FC Emmen']",
    ],
    "邓伯什": [
                "['Den Bosch']",
    ],
    "多德勒支": [
                "['Dordrecht']",
    ],
    "福伦丹": [
                "['FC Volendam']",
    ],
    "海尔蒙特": [
                "['Helmond Sport']",
    ],
    "格拉夫夏普": [
                "['De Graafschap']",
    ],
    "赫尔蒙尼蒂": [
                "['Heracles']",
    ],
    "赫尔蒙特": [
                "['Helmond Sport']",
    ],
    "罗达JC青年队": [
                "['Rodajc Youth']",
    ],
    "TOP奥斯": [
                "['TOP Oss']",
    ],
    "阿尔克马尔青年队": [
                "['AZ Youth']",
    ],
    "布雷达青年队": [
                "['NAC Breda Youth']",
    ],
    "芬洛": [
                "['Venlo']",
    ],
    "格拉夫夏普青年队": [
                "['Graafschap Youth']",
    ],
    "河床青年队": [
                "['River Plate Youth']",
    ],
    "赫拉克勒斯青年队": [
                "['Heracles Youth']",
    ],
    "赫尔曼尼蒂": [
                "['Heracles Almelo']",
    ],
    "赫尔蒙特体育": [
                "['Helmond Sport']",
    ],
    "赫尔蒙特体育青年队": [
                "['Helmond Sport Youth']",
    ],
    "里斯本竞技": [
                "['Sporting CP']",
    ],
    "法马利康": [
                "['Famalicão']",
    ],
    "费雷拉": [
                "['Ferreira']",
    ],
    "博阿维斯塔": [
                "['Boavista']",
    ],
    "里奥阿维": [
                "['Rio Ave']",
    ],
    "查韦斯": [
                "['Chaves']",
    ],
    "通德拉": [
                "['Tondela']",
    ],
    "埃斯托里尔": [
                "['Estoril Praia']",
    ],
    "葡萄牙国民": [
                "['Vitória SC']",
    ],
    "莫雷伦斯": [
                "['Moreirense']",
    ],
    "南安普顿": [
                "['Southampton']",
    ],
    "西布朗": [
                "['West Bromwich Albion']",
    ],
    "谢周三": [
                "['Sheffield Wednesday']",
    ],
    "布赖顿": [
                "['Brighton & Hove Albion']",
    ],
    "斯旺西": [
                "['Swansea City']",
    ],
    "QPR": [
                "['Queens Park Rangers']",
    ],
    "普雷斯顿": [
                "['Preston North End']",
    ],
    "斯托克城": [
                "['Stoke City']",
    ],
    "布莱克本": [
                "['Blackburn Rovers']",
    ],
    "米德尔斯堡": [
                "['Middlesbrough']",
    ],
    "伯明翰城": [
                "['Birmingham City']",
    ],
    "卢顿镇": [
                "['Luton Town']",
    ],
    "沃特福德": [
                "['Watford']",
    ],
    "布莱克浦": [
                "['Blackpool']",
    ],
    "加的夫城": [
                "['Cardiff City']",
    ],
    "德比郡": [
                "['Derby County']",
    ],
    "雷丁": [
                "['Reading FC']",
    ],
    "哈德斯菲尔德": [
                "['Huddersfield Town']",
    ],
    "布伦特福德": [
                "['Brentford FC']",
    ],
    "不莱梅": [
                "['Werder Bremen']",
    ],
    "厄尔士山奥厄": [
                "['Erzgebirge Aue']",
    ],
    "杜塞尔多夫": [
                "['Dusseldorf']",
    ],
    "凯泽斯劳滕": [
                "['Kaiserslautern']",
    ],
    "福图娜杜塞尔多夫": [
                "['Fortuna Dusseldorf']",
    ],
    "海登海姆": [
                "['Heidenheim']",
    ],
    "慕尼黑1860": [
                "['1860 Munich']",
    ],
    "奥格斯堡II": [
                "['Augsburg II']",
    ],
    "罗斯托克": [
                "['Rostock']",
    ],
    "柏林联合II": [
                "['Union Berlin II']",
    ],
    "汉诺威96": [
                "['Hannover 96']",
    ],
    "维尔茨堡踢球者": [
                "['Würzburger Kickers']",
    ],
    "因戈尔施塔特04": [
                "['Ingolstadt 04']",
    ],
    "达姆斯塔特98": [
                "['Darmstadt 98']",
    ],
    "德累斯顿迪纳摩": [
                "['Dresden Dynamo']",
    ],
    "明斯特": [
                "['Preußen Münster']",
    ],
    "美因茨05 II": [
                "['Mainz 05 II']",
    ],
    "纽伦堡II": [
                "['Nürnberg II']",
    ],
    "帕德博恩07 II": [
                "['Paderborn 07 II']",
    ],
    "桑德豪森": [
                "['Sandhausen']",
    ],
    "斯图加特II": [
                "['Stuttgart II']",
    ],
    "巴勒莫": [
                "['Palermo']",
    ],
    "斯佩齐亚": [
                "['Spezia']",
    ],
    "布雷西亚": [
                "['Brescia']",
    ],
    "巴里": [
                "['Bari']",
    ],
    "奇塔代拉": [
                "['Citadella']",
    ],
    "摩德纳": [
                "['Modena']",
    ],
    "佩斯卡拉": [
                "['Pescara']",
    ],
    "克雷莫内塞": [
                "['Cremonese']",
    ],
    "特里埃斯蒂纳": [
                "['Triestina']",
    ],
    "福贾": [
                "['Foggia']",
    ],
    "比萨": [
                "['Pisa']",
    ],
    "弗罗西诺内": [
                "['Frosinone']",
    ],
    "阿斯科利": [
                "['Ascoli']",
    ],
    "萨勒尼塔纳": [
                "['Salernitana']",
    ],
    "卢切塞": [
                "['Lucca']",
    ],
    "特拉帕尼": [
                "['Trapani']",
    ],
    "卡尔皮": [
                "['Carpi']",
    ],
    "甘冈": [
                "['Caen']",
    ],
    "奥尔良": [
                "['Orléans']",
    ],
    "巴斯蒂亚": [
                "['Bastia']",
    ],
    "奎维利": [
                "['Quimper']",
    ],
    "孔卡诺": [
                "['Concarneau']",
    ],
    "阿雅克肖": [
                "['Ajaccio']",
    ],
    "色当": [
                "['Sedan']",
    ],
    "亚眠": [
                "['Amiens SC']",
    ],
    "布尔格": [
                "['Bourg-en-Bresse']",
    ],
    "瓦朗谢纳": [
                "['Valenciennes']",
    ],
    "布雷斯特B": [
                "['Brest B']",
    ],
    "马默": [
                "['Malmö FF']",
    ],
    "埃尔夫斯堡": [
                "['Elfsborg']",
    ],
    "AIK索尔纳": [
                "['AIK']",
    ],
    "北雪平": [
                "['Norrköping']",
    ],
    "赫尔辛堡": [
                "['Helsingborg']",
    ],
    "IFK哥德堡": [
                "['IFK Göteborg']",
    ],
    "布rommapojkarna": [
                "['Brommapojkarna']",
    ],
    "厄勒布鲁": [
                "['Örebro SK']",
    ],
    "迪格弗斯": [
                "['Degerfors']",
    ],
    "瓦尔贝里": [
                "['Varbergs BoIS']",
    ],
    "诺科平": [
                "['Norrköping']",
    ],
    "希尔星堡": [
                "['Helsingborg']",
    ],
    "哈马比": [
                "['Hammarby']",
    ],
    "布洛马波卡纳": [
                "['Brommapojkarna']",
    ],
    "利勒斯特罗姆": [
                "['Lillestrøm']",
    ],
    "莫尔德": [
                "['Molde']",
    ],
    "海于格松": [
                "['Haugesund']",
    ],
    "斯特罗姆加斯特": [
                "['Strømsgodset']",
    ],
    "桑内斯": [
                "['Sogndal IL']",
    ],
    "布兰": [
                "['SK Brann']",
    ],
    "萨普斯堡08": [
                "['Sarpsborg 08']",
    ],
    "VPS瓦萨": [
                "['Vaasan Palloseura']",
    ],
    "拉赫蒂": [
                "['Lahti']",
    ],
    "塞伊奈约基": [
                "['Seinäjoen JK']",
    ],
    "玛丽港": [
                "['IFK Mariehamn']",
    ],
    "TPS图尔库": [
                "['TPS Turku']",
    ],
    "万塔": [
                "['Vaasa']",
    ],
    "哈卡": [
                "['HK Honka']",
    ],
    "INTERFOTO": [
                ,
    ],
    "流浪者": [
                "['Rangers']",
    ],
    "阿伯丁": [
                "['Aberdeen']",
    ],
    "希伯尼安": [
                "['Hibernian']",
    ],
    "邓迪联": [
                "['Dundee United']",
    ],
    "圣米伦": [
                "['St. Mirren']",
    ],
    "马瑟韦尔": [
                "['Motherwell']",
    ],
    "哈茨": [
                "['Hibernian']",
    ],
    "罗斯郡": [
                "['Ross County']",
    ],
    "基尔马诺克": [
                "['Kilmarnock']",
    ],
    "法尔科克": [
                "['Falkirk']",
    ],
    "帕尔蒂克": [
                "['Partick Thistle']",
    ],
    "安德莱赫特": [
                "['Anderlecht']",
    ],
    "标准列日": [
                "['Standard Liège']",
    ],
    "亨克": [
                "['KRC Genk']",
    ],
    "根特": [
                "['AA Gent']",
    ],
    "列日": [
                "['Liège']",
    ],
    "沙勒罗瓦": [
                "['Charleroi']",
    ],
    "威尔郡": [
                "['Westerlo']",
    ],
    "梅赫伦": [
                "['Mechelen']",
    ],
    "欧本": [
                "['OH Leuven']",
    ],
    "圣图尔登": [
                "['Sint-Truiden']",
    ],
    "洛克伦": [
                "['Lokeren']",
    ],
    "祖尔特瓦雷根": [
                "['Zulte Waregem']",
    ],
    "科特赖克": [
                "['Kortrijk']",
    ],
    "皇家charleroi": [
                "['Charleroi']",
    ],
    "皇家genk": [
                "['KRC Genk']",
    ],
    "皇家安特卫普": [
                "['Royal Antwerp']",
    ],
    "皇家标准列日": [
                "['Standard Liège']",
    ],
    "特拉布宗体育": [
                "['Trabzonspor']",
    ],
    "巴沙克舒希尔": [
                "['Başakşehir']",
    ],
    "卡塞利体育": [
                "['Kayserispor']",
    ],
    "安塔利亚体育": [
                "['Antalyaspor']",
    ],
    "阿兰亚斯堡": [
                "['Alanyaspor']",
    ],
    "哈塔伊体育": [
                "['Hatayspor']",
    ],
    "伊斯坦布尔BB": [
                "['Istanbul BB']",
    ],
    "开塞利体育": [
                "['Kayserispor']",
    ],
    "科尼亚体育": [
                "['Konyaspor']",
    ],
    "锡瓦斯体育": [
                "['Sivasspor']",
    ],
    "代尼兹利体育": [
                "['Denizlispor']",
    ],
    "加济安泰普体育": [
                "['Gaziantep FK']",
    ],
    "埃拉泽体育": [
                "['Elazigspor']",
    ],
    "阿达纳体育": [
                "['Adanaspor']",
    ],
    "尤姆尼耶体育": [
                "['Yomanyesehirspor']",
    ],
    "卡拉比克体育": [
                "['Karabukspor']",
    ],
    "阿尔特荣": [
                "['Altay']",
    ],
    "泽尼特": [
                "['Zenit']",
    ],
    "莫斯科中央陆军": [
                "['CSKA Moscow']",
    ],
    "莫斯科迪纳摩": [
                "['Dynamo Moscow']",
    ],
    "洛科莫特夫": [
                "['Lokomotiv Moscow']",
    ],
    "斯巴达": [
                "['Spartak Moscow']",
    ],
    "克拉斯诺达尔": [
                "['Krasnodar']",
    ],
    "罗斯托夫": [
                "['Rostov']",
    ],
    "火车头": [
                "['Lokomotiv Moscow']",
    ],
    "乌拉尔": [
                "['Ural']",
    ],
    "喀山红宝石": [
                "['Rubin Kazan']",
    ],
    "奥伦堡": [
                "['Orenburg']",
    ],
    "秋明": [
                "['Tyumen']",
    ],
    "诺夫哥罗德": [
                "['Novgorod']",
    ],
    "巴尔瑙尔纵火犯": [
                "['Torpedo-BelAZ']",
    ],
    "坦波夫": [
                "['Tambov']",
    ],
    "阿赫马特": [
                "['Akhmat Grozny']",
    ],
    "伏尔加格勒": [
                "['Volgograd']",
    ],
    "巴塞尔": [
                "['FC Basel']",
    ],
    "年轻人": [
                "['Young Boys']",
    ],
    "锡永": [
                "['Sion']",
    ],
    "卢塞恩": [
                "['Lucerne']",
    ],
    "圣加伦": [
                "['St. Gallen']",
    ],
    "温特图尔": [
                "['Winterthur']",
    ],
    "苏黎世草蜢": [
                "['Grasshopper']",
    ],
    "卢加诺": [
                "['Lugano']",
    ],
    "阿劳": [
                "['Aarau']",
    ],
    "苏黎世": [
                "['FC Zürich']",
    ],
    "哥本哈根": [
                "['FC København']",
    ],
    "中日德兰": [
                "['Midtjylland']",
    ],
    "布隆德比": [
                "['Brøndby']",
    ],
    "北西兰": [
                "['Nordsjælland']",
    ],
    "奥尔胡斯": [
                "['Aarhus']",
    ],
    "欧登塞": [
                "['Odense']",
    ],
    "桑德捷斯基": [
                "['Sønderjyske']",
    ],
    "锡尔克堡": [
                "['Silkeborg']",
    ],
    "瓦埃勒": [
                "['Vejle']",
    ],
    "霍森斯": [
                "['Horsens']",
    ],
    "维堡": [
                "['Viborg']",
    ],
    "米德法特": [
                "['Middelfart']",
    ],
    "洛斯查兰特": [
                "['Roskilde']",
    ],
    "宁比": [
                "['Nykøbing']",
    ],
    "奥尔堡": [
                "['Aalborg']",
    ],
    "帕纳辛奈科斯": [
                "['Panathinaikos']",
    ],
    "奥林匹亚科斯": [
                "['Olympiacos']",
    ],
    "AEK雅典": [
                "['AEK Athens']",
    ],
    "拉里萨": [
                "['Larissa']",
    ],
    "潘斯拉基科斯": [
                "['Panthrakikos']",
    ],
    "帕纳多里基高斯": [
                "['Panachaiki']",
    ],
    "阿里斯": [
                "['Aris Thessaloniki']",
    ],
    "普雷韦扎": [
                "['Preveza']",
    ],
    "伊奥尼科斯": [
                "['Ionikos']",
    ],
    "特里波利斯": [
                "['Trikala']",
    ],
    "帕纳察治": [
                "['Panachaiki']",
    ],
    "卡维拉": [
                "['Kavala']",
    ],
    "沃罗斯": [
                "['Volos NFC']",
    ],
    "阿特罗米托斯": [
                "['Atromitos']",
    ],
    "潘塞莱尼克": [
                "['Panetolikos']",
    ],
    "艾格纳提亚": [
                "['Egnatia']",
    ],
    "卡利地亚": [
                "['Kallithea']",
    ],
    "伊拉克利斯": [
                "['Iraklis']",
    ],
    "科孚": [
                "['Kerkyra']",
    ],
    "OFI克里特": [
                "['OFI Crete']",
    ],
    "CF蒙特利尔": [
                "['CF Montreal']",
    ],
    "利雅得新月": [
                "['Al Hilal']",
    ],
    "利雅得胜利": [
                "['Al Nassr']",
    ],
    "伊蒂哈德": [
                "['Al Ittihad']",
    ],
    "阿尔萨德": [
                "['Al Sadd']",
    ],
    "阿尔艾因": [
                "['Al Ain']",
    ],
    "德黑兰独立": [
                "['Esteghlal']",
    ],
    "波斯波利斯": [
                "['Persepolis']",
    ],
    "阿尔杜海勒": [
                "['Al Dhaffra']",
    ],
    "水原三星": [
                "['Suwon Samsung']",
    ],
    "名古屋鲸八": [
                "['Nagoya Grampus']",
    ],
    "泰国BG巴吞联": [
                "['BG Pathum United']",
    ],
    "越南河内": [
                "['Hanoi FC']",
    ],
    "马来西亚柔佛": [
                "['Johor DT']",
    ],
    "新加坡": [
                "['Lion City Sailors']",
    ],
    "澳大利亚墨尔本城": [
                "['Melbourne City']",
    ],
    "日本东京FC": [
                "['FC Tokyo']",
    ],
    "韩国浦项制铁": [
                "['Pohang Steelers']",
    ],
    "卡塔尔阿尔萨德": [
                "['Al Sadd']",
    ],
    "沙特利雅得新月": [
                "['Al Hilal']",
    ],
    "伊朗波斯波利斯": [
                "['Persepolis']",
    ],
    "阿联酋阿尔艾因": [
                "['Al Ain']",
    ],
    "科特赖���": [
                "['Kortrijk']",
    ],
}

def query_telegram_tips_for_match(home, away):
    """从 predictions.db 真实调取海外多个推单频道的实盘方案与情报"""
    if not os.path.exists(DB_PATH):
        return []

    # 统一加载 team_aliases.json（覆盖所有联赛，不在代码里分散维护）
    _alias_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "team_aliases.json")
    try:
        with open(_alias_path, encoding="utf-8") as _f:
            _TEAM_ALIAS = json.load(_f)
    except Exception:
        _TEAM_ALIAS = {}

    # 联赛关键词映射：用于过滤和加权不同联赛的情报
    LEAGUE_KEYWORDS = {
        "英超": ["premier", "epl", "england", "manchester", "liverpool", "chelsea", "arsenal", "tottenham", "united"],
        "西甲": ["laliga", "la liga", "spain", "real madrid", "barcelona", "atletico", "sevilla", "valencia"],
        "意甲": ["seriea", "serie a", "italia", "juventus", "milan", "inter", "napoli", "roma", "lazio"],
        "德甲": ["bundesliga", "germany", "bayern", "dortmund", "leverkusen", "leipzig", "frankfurt"],
        "法甲": ["ligue1", "ligue 1", "france", "psg", "paris", "marseille", "lyon", "monaco"],
        "欧冠": ["champions league", "ucl", "champions", "欧冠"],
        "欧联": ["europa league", "uel", "欧联"],
        "欧协联": ["conference league", "uecl", "欧协联"],
        "日职": ["j league", "j1", "j2", "japan", "fc tokyo", "kashima", "vissel", "kawasaki"],
        "日乙": ["j2 league", "japan j2"],
        "韩职": ["k league", "korea", "seoul", "ulsan", "jeonbuk", "pohang"],
        "巴甲": ["brasileirao", "brasileir", "brazil", "palmeiras", "flamengo", "sao paulo"],
        "澳超": ["a-league", "australia", "sydney", "melbourne", "adelaide"],
        "挪超": ["eliteserien", "norway", "bodø", "molde", "roasenborg", "tromsø"],
        "瑞超": ["allsvenskan", "sweden", "malmo", "djurgården", "elfsborg", "sirius"],
        "芬超": ["veikkaus", "finland", "hjk", "kuopio", "tps"],
        "荷甲": ["eredivisie", "netherlands", "ajax", "feyenoord", "psv", "alkmaar"],
        "荷乙": ["eerste divisie", "netherlands second"],
        "葡超": ["primeira liga", "portugal", "benfica", "porto", "braga"],
        "英冠": ["championship", "england championship"],
        "德甲2": ["2.bundesliga", "germany second"],
        "意甲2": ["serie b", "italy second"],
        "法乙": ["ligue 2", "france second"],
        "解放者杯": ["libertadores", "copa libertadores", "南美解放者杯"],
    }

    # 根据主队或客队名推断比赛所属联赛
    def infer_league(home, away):
        home_lower = home.lower()
        away_lower = away.lower()
        combined = f"{home_lower} {away_lower}"
        detected = []
        for league, keywords in LEAGUE_KEYWORDS.items():
            if any(kw in combined for kw in keywords):
                detected.append(league)
        return detected if detected else ["综合"]

    detected_leagues = infer_league(home, away)

    # 加载 team_aliases.json（运行时加载确保最新）
    _alias_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "team_aliases.json")
    try:
        with open(_alias_path, encoding="utf-8") as _f:
            _TEAM_ALIAS = json.load(_f)
    except Exception:
        _TEAM_ALIAS = {}

    h_keys = [home.lower()] + ALIAS_MAP.get(home, []) + _TEAM_ALIAS.get(home, [])
    a_keys = [away.lower()] + ALIAS_MAP.get(away, []) + _TEAM_ALIAS.get(away, [])

    # 标准化关键词：移除特殊字符，统一格式
    def normalize_key(k):
        return k.replace('ø', 'o').replace('ø', 'o').replace('/', '').replace('-', ' ').lower()

    h_keys_norm = [normalize_key(k) for k in h_keys]
    a_keys_norm = [normalize_key(k) for k in a_keys]

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT channel, raw_text, post_time 
        FROM telegram_tips 
        ORDER BY id DESC LIMIT 2000
    """)
    c = conn.cursor()
    c.execute("""
        SELECT channel, raw_text, post_time 
        FROM telegram_tips 
        ORDER BY id DESC LIMIT 2000
    """)
    rows = c.fetchall()
    conn.close()
    
    matched = []
    # 全量统计海外 100 个频道对该场比赛的倾向分布与高信度论据
    sentiment = {"home_win": 0, "away_win": 0, "draw_or_double": 0, "over_goals": 0, "handicap": 0}
    featured_arguments = []

    for ch, raw, pt in rows:
        if not raw: continue
        low = raw.lower()
        # 使用标准化关键词匹配
        has_h = any(normalize_key(k) in low for k in h_keys if len(k) >= 3)
        has_a = any(normalize_key(k) in low for k in a_keys if len(k) >= 3)
        if has_h or has_a:
            clean = raw.replace('\n', ' ')
            clean = re.sub(r'http\S+', '', clean).strip()
            
            # 端侧极速语义标签解析（0 额度消耗，全量感知海外大盘）
            if any(w in low for w in ['win', ' 1 ', '1x2: 1', 'home win', 'vitoria', 'gana']):
                if has_h and not has_a: sentiment['home_win'] += 1
                elif has_a and not has_h: sentiment['away_win'] += 1
                else: sentiment['home_win'] += 1
            elif any(w in low for w in ['x2', '1x', 'draw', 'empate', 'pareggio', 'double chance', 'underdog']):
                sentiment['draw_or_double'] += 1
            elif any(w in low for w in ['over 2.5', 'over 3.5', 'btts', 'both teams to score', 'mas de']):
                sentiment['over_goals'] += 1
            elif any(w in low for w in ['ah ', 'handicap', '-1', '-1.5', '+1']):
                sentiment['handicap'] += 1

            matched.append({
                "channel": ch,
                "text": clean[:110],
                "time": pt
            })
            if any(w in low for w in ['injury', 'lineup', 'absent', 'suspension', 'official', 'news', 'key']) and len(featured_arguments) < 4:
                featured_arguments.append(f"[@{ch}更衣室]: {clean[:90]}")

    total_matched = len(matched)
    return {
        "total_matched": total_matched,
        "sentiment": sentiment,
        "featured_arguments": featured_arguments,
        "sample_tips": matched[:8] # 精选前 8 条最新鲜出单
    }

def compute_poisson_and_kelly(odds, league="", is_only_rq=False, rang="0"):
    """模型一 (Low 极端数学): 双变量泊松分布 (Bivariate Poisson) 与凯利去水比分精算"""
    try:
        sp_h = float(odds[0]) if odds[0] != '-' else 2.5
        sp_d = float(odds[1]) if odds[1] != '-' else 3.2
        sp_a = float(odds[2]) if odds[2] != '-' else 2.8
    except:
        sp_h, sp_d, sp_a = 2.0, 3.2, 3.0

    # 返还率与纯净概率 (消除机构水钱抽成)
    p_h = 1.0 / sp_h
    p_d = 1.0 / sp_d
    p_a = 1.0 / sp_a
    total_p = p_h + p_d + p_a
    margin = (total_p - 1.0) * 100 # 机构抽水率
    pure_h = (p_h / total_p) * 100
    pure_d = (p_d / total_p) * 100
    pure_a = (p_a / total_p) * 100

    # 凯利去水打分 (0-100)
    odds_score = round(min(max(pure_h * 1.1 if pure_h >= pure_a else pure_a * 1.1, 60.0), 86.0), 1)

    # 动态联赛与强弱梯度修正基准进球权重 (破除死板的平均值禁锢)
    base_goal_factor = 1.35
    if league in ['荷甲', '德甲', '美职足', '瑞士超']:
        base_goal_factor = 1.65 # 天然大球高开联赛
    elif league in ['意甲', '西甲', '法乙', '西乙']:
        base_goal_factor = 1.15 # 典型防守绞杀联赛

    # 单开让球特殊处理：若是主让深盘（如让2球），皇马的真实净胜能力必须还原！
    if is_only_rq and int(rang) <= -2:
        # 深盘让球局，主队属于超级豪门狂攻格局，基准期望值必须大幅提升
        lambda_h = max(2.2, min(4.0, 2.65))
        mu_a = max(0.5, min(1.8, 0.95))
    else:
        # 基于胜平负概率反推攻防期望值 (Lambda: 主队 xG, Mu: 客队 xG)
        ratio_ha = pure_h / (pure_h + pure_a + 1e-5)
        lambda_h = max(0.6, min(3.8, base_goal_factor * (ratio_ha / 0.5)))
        mu_a = max(0.4, min(3.5, (base_goal_factor - 0.1) * ((1.0 - ratio_ha) / 0.5)))

    # 二维双变量泊松分布计算 0-0 到 5-4 共 30 个比分的理论概率
    score_probs = {}
    for x in range(6):
        for y in range(5):
            prob_x = (lambda_h ** x) * math.exp(-lambda_h) / math.factorial(x)
            prob_y = (mu_a ** y) * math.exp(-mu_a) / math.factorial(y)
            score_probs[f"{x}-{y}"] = prob_x * prob_y

    # 取数学概率最高的 Top 5 纯理论比分
    sorted_scores = sorted(score_probs.items(), key=lambda kv: kv[1], reverse=True)
    top_math_scores = [s[0] for s in sorted_scores[:5]]

    return {
        "sp_h": sp_h, "sp_d": sp_d, "sp_a": sp_a,
        "pure_h": round(pure_h, 1),
        "pure_d": round(pure_d, 1),
        "pure_a": round(pure_a, 1),
        "margin": round(margin, 1),
        "odds_score": odds_score,
        "lambda_h": round(lambda_h, 2),
        "mu_a": round(mu_a, 2),
        "top_math_scores": top_math_scores
    }

def run_tri_model_deep_reasoning(match_info):
    """
    启动最高难度三模型交叉推演：
    1. Low 模型: 凯利去水与泊松分布理论概率
    2. High 模型 (战术矛盾 & 诱盘阻水反推)
    3. High 满血模型 (海外 22 频道实盘共振 & 爆冷路径对抗审查)
    """
    code = match_info['code']
    home = match_info['home']
    away = match_info['away']
    league = match_info['league']
    odds = match_info.get('odds', ['2.0', '3.2', '3.0'])
    is_only_rq = match_info.get('is_only_rq', False)
    rang = match_info.get('rang', '0')

    # 1. 运行 Low 模型计算物理数学指标 (按联赛大球属性与攻防因子动态修正)
    stats = compute_poisson_and_kelly(odds, league=league, is_only_rq=is_only_rq, rang=rang)

    # 2. 调取真实海外 100 个电报频道推单（全量提取提纯，结构化归纳）
    tg_data = query_telegram_tips_for_match(home, away)
    if isinstance(tg_data, dict):
        total_m = tg_data.get('total_matched', 0)
        senti = tg_data.get('sentiment', {})
        sample_tips = tg_data.get('sample_tips', [])
        feat_args = tg_data.get('featured_arguments', [])
        
        tg_context = f"【海外100频道全量情报全息画像】(共深度检索到 {total_m} 条真实讨论与推单)\n"
        tg_context += f"- 欧洲各流派实盘倾向统计：主胜倾向 {senti.get('home_win', 0)} 票 | 客胜倾向 {senti.get('away_win', 0)} 票 | 双选防平/爆冷 {senti.get('draw_or_double', 0)} 票 | 大小球进球数 {senti.get('over_goals', 0)} 票 | 让球盘口 {senti.get('handicap', 0)} 票\n"
        if feat_args:
            tg_context += "- 提炼出的更衣室/伤停特情：" + "；".join(feat_args) + "\n"
        if sample_tips:
            tg_context += "- 欧洲前线代表性出单样本：\n" + "\n".join([f"  * [{t['channel']}]: {t['text']}" for t in sample_tips[:6]])
    else:
        tg_context = "暂无该场直连推单，参考欧洲欧赔大盘整体流向。"

    # 3. 构造最高难度红蓝对抗 Prompt，调用本地 gemini-3.8-flash-high 满血推理
    prompt = f"""你是一名拥有20年实战操盘经验的中国体育彩票资深分析导师，同时担任欧洲职业足球红蓝对抗审计专家。
请对以下即将开赛的【中国体育彩票】在售赛事进行最高难度级别的全息推演：

【赛事信息】
- 编号与联赛：{code} {league}
- 对阵双方：{home} (主队) VS {away} (客队)
- 官方SP赔率：主胜 {stats['sp_h']} | 平局 {stats['sp_d']} | 客胜 {stats['sp_a']}
- 是否单开让球胜平负：{'是 (主让' + rang + '球)' if is_only_rq else '否 (标准胜平负)'}
- 数学去水指标：主胜真实概率 {stats['pure_h']}% | 平局 {stats['pure_d']}% | 客胜 {stats['pure_a']}% (机构抽水 {stats['margin']}%)
- 【模型一：二维双变量泊松分布精算】：主队xG进球期望 {stats['lambda_h']} | 客队xG进球期望 {stats['mu_a']} | 纯数学理论Top5高频比分: {stats['top_math_scores']}
- 海外22个推单频道前线情报/推单捕捉：
{tg_context}

【强制推演三阶要求】
第一阶段：【High满血战术矛盾与进球格局推演】
1. 深入分析两队战术阵眼：主队破大巴效率 vs 客队防守反击纵深速度。
2. 比赛节奏与总进球数格局：是防守绞杀的肉搏战（0-2球小球带），还是互攻穿透的大球格局（3-5球大球带）？豪门是否存在垃圾时间补时刷球溢出能力？
3. 识别机构意图：官方 SP 水位是否存在阻上或诱下？平局是否被机构刻意低赔防范？

第二阶段：【High满血红蓝对抗挑刺 (破坏者视角)】
以破坏者视角反思：如果强队打不出来或正路爆冷，最致命的客观原因会是什么？绝不能给出没有防范的盲目死胆！

第三阶段：【终极仲裁决策与【黄金三角】比分输出】
1. 赛前研判建议选项（必须为中国体彩合法出票选项）：
   - 若单开让球：必须为【让胜/博穿盘】、【让负/首选客不败】或【让平/防让胜】；
   - 若标准双开：必须为【主胜】、【客胜】、【主不败/首选主胜】、【客不败/双选平负】或【平局/防冷】；
2. 【核心重点：比分实战黄金三角组合（严密防范）】：
   - 必须给出 3 个高确定性比分，且严禁全部扎堆在同一个总进球数里！
   - 必须涵盖【① 核心正路高频比分】+【② 零封/闷杀保守比分】+【③ 穿盘/互攻防爆比分】构成的黄金三角矩阵！
   - 严格参考模型一泊松高频比分 {stats['top_math_scores']} 与战术格局，杜绝方向看对但比分差一个球的遗憾！
3. 给出四维因子打分（0-100）并严格遵循加权共识算法（【最高绝对权重：海外实盘共振 60%】）：
   - odds_score: 盘口去水打分（权重 15%）
   - intel_score: 更衣室暗流打分（权重 15%）
   - tipster_score: 海外实盘共振打分（【核心绝对主导 60%】：欧洲22个专业频道真金白银实盘方案与专家共识，作为全盘第一决定性权重！）
   - math_score: 战力泊松打分（权重 10%）
   - consensus_ratio: 综合共识百分比，计算公式为：(odds_score * 0.15) + (intel_score * 0.15) + (tipster_score * 0.60) + (math_score * 0.10)
   【铁律】：海外推单频道如果有明确方案和专家共识，tipster_score 必须直接给高分（85~95 分），且其研判倾向拥有绝对主导权，必须作为赛前建议选项与黄金三角比分防范的第一基石！

【输出 JSON 契约】：
请严格仅返回纯 JSON 对象（不要有任何 markdown 代码块包裹，不要有多余废话）：
{{
  "tip": "推荐选项",
  "consensus_ratio": 76.5,
  "consensus_breakdown": {{
    "odds_score": 75.0,
    "intel_score": 78.0,
    "tipster_score": 76.0,
    "math_score": 74.0
  }},
  "predicted_goals": ["2", "3"],
  "predicted_scores": ["比分1", "比分2", "比分3"],
  "fundamental": "一、联赛积分与基本面战意格局详细解析（100字左右，结合真实近况与地利）",
  "tactical_conflict": "二、核心战术矛盾与人员阵眼详细解析（100字左右，突出攻坚与反击关键点）",
  "market_attitude": "三、欧洲37家机构盘口与去水态度详细解析（100字左右，必须准确引用真实赔率数值）",
  "decision_guide": "四、小杨店主研判与选择指引详细解析（100字左右，明确告诉彩民怎么出票、进球数怎么选、比分怎么防）"
}}
"""

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LLM_KEY}"
    }
    payload = {
        "model": "gemini-3.8-flash-low",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2
    }

    req = urllib.request.Request(LLM_URL, data=json.dumps(payload).encode('utf-8'), headers=headers)
    with urllib.request.urlopen(req, timeout=90) as resp:
        result = json.loads(resp.read().decode('utf-8'))
        raw_output = result['choices'][0]['message']['content'].strip()
        
        # 稳健提取 JSON 字符串（提取首个 '{' 到最后一个 '}' 之间的内容，抗思维链与冗余文本干扰）
        match_json = re.search(r'(\{[\s\S]*\})', raw_output)
        if match_json:
            clean_json = match_json.group(1)
        else:
            clean_json = raw_output
            
        clean_json = re.sub(r'^```json\s*', '', clean_json)
        clean_json = re.sub(r'^```\s*', '', clean_json)
        clean_json = re.sub(r'\s*```$', '', clean_json)
        
        parsed = json.loads(clean_json)
        # 字段完整性契约兜底校验
        for req_k in ["tip", "consensus_ratio", "predicted_scores", "fundamental", "tactical_conflict", "market_attitude", "decision_guide"]:
            if req_k not in parsed:
                raise ValueError(f"Missing required field in LLM response: {req_k}")
        return parsed

if __name__ == "__main__":
    # 测试单场比赛推演
    test_match = {
        "code": "周日021",
        "league": "西甲",
        "home": "马拉加",
        "away": "皇家社会",
        "odds": ["3.08", "3.35", "1.98"],
        "is_only_rq": False,
        "rang": "0"
    }
    print("开始测试 High 满血模型交叉对抗推演...")
    res = run_tri_model_deep_reasoning(test_match)
    print("\n推演产物结果:")
    print(json.dumps(res, ensure_ascii=False, indent=2))
