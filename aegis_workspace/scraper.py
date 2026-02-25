import requests
from bs4 import BeautifulSoup

url = "https://en.wikipedia.org/wiki/Web_scraping"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

response = requests.get(url, headers=headers)

if response.status_code == 200:
    soup = BeautifulSoup(response.content, 'html.parser')
    
    content = soup.find(id="mw-content-text")
    if content:
        text = content.get_text(separator='\n', strip=True)
    else:
        text = soup.get_text(separator='\n', strip=True)
        
    with open("wikipedia_scraping.txt", "w", encoding="utf-8") as f:
        f.write(text)
    print("Scraping successful. Saved to wikipedia_scraping.txt")
else:
    print(f"Failed to retrieve page. Status code: {response.status_code}")