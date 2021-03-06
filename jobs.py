from apscheduler.schedulers.blocking import BlockingScheduler
import os, json, calendar, re
import ssl, logging
from time import time
from datetime import timedelta, datetime
from urllib.parse import urlparse, quote_plus
import urllib.request
import redis

sched = BlockingScheduler()

USER_AGENT = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_12_1) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/54.0.2840.98 Safari/537.36"
}


def index_get(array, *argv):
    """
    checks if a index is available in the array and returns it
    :param array: the data array
    :param argv: index integers
    :return: None if not available or the return value
    """
    try:
        for index in argv:
            array = array[index]
        return array
    # there is either no info available or no popular times
    # TypeError: rating/rating_n/populartimes wrong of not available
    except (IndexError, TypeError):
        return None


def get_pop_times(places):
    params_url = {
        "tbm": "map",
        "tch": 1,
        "hl": "en",
        "q": urllib.parse.quote_plus(places),
        "pb": "!4m12!1m3!1d4005.9771522653964!2d-122.42072974863942!3d37.8077459796541!2m3!1f0!2f0!3f0!3m2!1i1125!2i976"
        "!4f13.1!7i20!10b1!12m6!2m3!5m1!6e2!20e3!10b1!16b1!19m3!2m2!1i392!2i106!20m61!2m2!1i203!2i100!3m2!2i4!5b1"
        "!6m6!1m2!1i86!2i86!1m2!1i408!2i200!7m46!1m3!1e1!2b0!3e3!1m3!1e2!2b1!3e2!1m3!1e2!2b0!3e3!1m3!1e3!2b0!3e3!"
        "1m3!1e4!2b0!3e3!1m3!1e8!2b0!3e3!1m3!1e3!2b1!3e2!1m3!1e9!2b1!3e2!1m3!1e10!2b0!3e3!1m3!1e10!2b1!3e2!1m3!1e"
        "10!2b0!3e4!2b1!4b1!9b0!22m6!1sa9fVWea_MsX8adX8j8AE%3A1!2zMWk6Mix0OjExODg3LGU6MSxwOmE5ZlZXZWFfTXNYOGFkWDh"
        "qOEFFOjE!7e81!12e3!17sa9fVWea_MsX8adX8j8AE%3A564!18e15!24m15!2b1!5m4!2b1!3b1!5b1!6b1!10m1!8e3!17b1!24b1!"
        "25b1!26b1!30m1!2b1!36b1!26m3!2m2!1i80!2i92!30m28!1m6!1m2!1i0!2i0!2m2!1i458!2i976!1m6!1m2!1i1075!2i0!2m2!"
        "1i1125!2i976!1m6!1m2!1i0!2i0!2m2!1i1125!2i20!1m6!1m2!1i0!2i956!2m2!1i1125!2i976!37m1!1e81!42b1!47m0!49m1"
        "!3b1",
    }

    search_url = "https://www.google.de/search?" + "&".join(
        k + "=" + str(v) for k, v in params_url.items()
    )

    # noinspection PyUnresolvedReferences
    gcontext = ssl.SSLContext(ssl.PROTOCOL_TLSv1)

    resp = urllib.request.urlopen(
        urllib.request.Request(url=search_url, data=None, headers=USER_AGENT),
        context=gcontext,
    )

    data = resp.read().decode("utf-8").split('/*""*/')[0]

    # find eof json
    jend = data.rfind("}")
    if jend >= 0:
        data = data[: jend + 1]

    jdata = json.loads(data)["d"]
    jdata = json.loads(jdata[4:])

    # get info from result array, has to be adapted if backend api changes
    info = index_get(jdata, 0, 1, 0, 14)

    # current_popularity is also not available if popular_times isn't
    current_popularity = index_get(info, 84, 7, 1)
    if current_popularity == None:
        current_popularity = 0

    popular_times = index_get(info, 84, 0)

    return current_popularity, popular_times


def get_popularity_for_day(popularity):
    """
    Returns popularity for day
    :param popularity:
    :return:
    """

    # Initialize empty matrix with 0s
    pop_json = [[0 for _ in range(24)] for _ in range(7)]

    for day in popularity:
        day_no, pop_times = day[:2]
        if pop_times:
            for hour_info in pop_times:
                hour = hour_info[0]
                pop_json[day_no - 1][hour] = hour_info[1]
                # day wrap
                if hour_info[0] == 23:
                    day_no = day_no % 7 + 1
    ret_popularity = [
        {"name": list(calendar.day_name)[d], "data": pop_json[d]} for d in range(7)
    ]
    return ret_popularity


@sched.scheduled_job("interval", minutes=15)
def timed_job():
    # Run through all location, get current popularity and popular times
    # Store data to redis cloud

    start = time()

    # Connect to rediscloud
    url = urlparse(os.environ.get("REDISCLOUD_URL"))
    r = redis.StrictRedis(
        host=url.hostname,
        port=url.port,
        password=url.password,
        charset="utf-8",
        decode_responses=True,
    )

    # Get current date time
    curr_time = datetime.now()
    curr_hour = curr_time.hour
    today_date = int(
        datetime.timestamp(datetime(curr_time.year, curr_time.month, curr_time.day))
    )

    # Get redis data
    redis_data = json.loads(r.get("data"))

    # Get all places from json
    with open("places.json", "r") as f:
        places = json.load(f)
    with open("address.json", "r") as f:
        address = json.load(f)
    places_set = set()
    for place_type in places:
        for place in places[place_type]:
            places_set.add(place)

    # Compare redis data with json data
    # Delete location from redis that are not in json
    for k in redis_data.keys() - places_set:
        del r[k]

    # Add new location to redis that are in json
    for k in places_set - redis_data.keys():
        redis_data[k] = {"current_popularity": [0, 0, 0, 0, 0, 0, 0, 0, 0]}

    # Redis cloud max storage is 30mb, need to delete past data to have enough storage for new data
    days_keys = sorted(
        [int(k) for k in r.keys() if k not in {"last_updated", "time_taken", "data"}]
    )
    if len(days_keys) > 60:
        r.delete(str(days_keys[0]))

    # Check if day data exist in redis, if not exist create new key (for analysis)
    if str(today_date) not in r.keys():
        day_data = {
            place: {str(i): [] for i in range(24)} for place in redis_data.keys()
        }
    else:
        day_data = json.loads(r.get(str(today_date)))

    # Get and store crowd data
    for k in redis_data:
        current_popularity = redis_data[k]["current_popularity"]
        if address.get(k):
            new_k = k + ", " + address[k]
        else:
            new_k = k
        current_pop, pop_times = get_pop_times(new_k)
        current_popularity.remove(current_popularity[0])
        current_popularity.append(current_pop)
        if pop_times:
            redis_data[k]["popular_times"] = get_popularity_for_day(pop_times)
        else:
            redis_data[k]["popular_times"] = []
        day_data[k][str(curr_hour)].append(current_pop)
    r.set(name=str(today_date), value=json.dumps(day_data))
    r.set(name="data", value=json.dumps(redis_data))
    creation_time = int(time())
    r.set(name="last_updated", value=creation_time)
    time_taken = time() - start
    r.set(name="time_taken", value=str(time_taken))


sched.start()
