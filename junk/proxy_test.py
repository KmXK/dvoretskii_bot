import asyncio
import logging

import youtube_dl

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.DEBUG)

async def main():
    # proxy_handler = urllib.request.ProxyHandler({'http': 'http://nigger.by:61228'})
    # proxy_auth = urllib.request.ProxyBasicAuthHandler()
    # proxy_auth.add_password('realm', 'nigger.by:61228', '***REMOVED***', '***REMOVED***')

    # opener = urllib.request.build_opener(proxy_handler, proxy_auth)
    # # urllib.request.install_opener(opener)

    # print(urllib.request.urlopen('http://api.ip.sb/jsonip').read().decode('utf-8'))

    # resp: http.client.HTTPResponse = urllib.request.urlopen('http://google.com/')
    # print(resp.status, resp.reason)
    # print(resp.read().decode('utf-8'))

    print(youtube_dl.YoutubeDL({
        'proxy': 'socks5://***REMOVED***:***REMOVED***@nigger.by:61228',
        'forceurl': True,
        'youtube_include_dash_manifest': False,
        'username': 'dvoretskii.bot@gmail.com',
        'password': '***REMOVED***',
        'verbose': True
    }).extract_info('https://youtube.com/watch?v=rF72jrSYhEE',download=False))


if __name__ == "__main__":
    asyncio.run(main())