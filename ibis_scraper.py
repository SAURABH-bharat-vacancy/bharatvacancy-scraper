import requests
from bs4 import BeautifulSoup
import csv
from datetime import datetime
import re

def scrape_ibps_jobs():
    """Scrape IBPS job notifications"""
    
    jobs = []
    
    try:
        # IBPS main notifications page
        url = "https://ibpsonline.ibps.in/recruit/"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Find all job notification links
        # IBPS typically has news/notification sections
        notification_divs = soup.find_all('div', class_=['news-item', 'notification', 'update'])
        
        # Fallback: look for links containing recruitment keywords
        if not notification_divs:
            links = soup.find_all('a', href=re.compile(r'recruit|notification|notice|job', re.I))
        else:
            links = []
            for div in notification_divs:
                links.extend(div.find_all('a'))
        
        for link in links:
            text = link.get_text(strip=True)
            href = link.get('href', '')
            
            # Filter for actual job postings
            if any(keyword in text.lower() for keyword in ['recruitment', 'notification', 'officer', 'clerk', 'specialist']):
                if not href:
                    href = url
                
                # Build job entry
                job = {
                    'title': text[:100],  # Limit to 100 chars
                    'company': 'IBPS',
                    'location': 'All India',
                    'category': 'Banking',
                    'job_type': 'Permanent',
                    'application_link': href if href.startswith('http') else url + href,
                    'description': text[:200]
                }
                jobs.append(job)
        
        print(f"✓ Scraped {len(jobs)} IBPS job notifications")
        return jobs
    
    except Exception as e:
        print(f"✗ IBPS scraping failed: {str(e)}")
        return []


def save_ibps_csv(jobs):
    """Save IBPS jobs to CSV in WordPress import format"""
    
    if not jobs:
        print("No IBPS jobs to save")
        return
    
    # Remove duplicates by title
    unique_jobs = {job['title']: job for job in jobs}
    jobs = list(unique_jobs.values())
    
    # Save in WordPress import format
    with open('ibps_import.csv', 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'title', 'company', 'location', 'category', 'job_type', 'application_link', 'description'
        ])
        writer.writeheader()
        writer.writerows(jobs)
    
    print(f"✓ Saved {len(jobs)} IBPS jobs to ibps_import.csv")


if __name__ == "__main__":
    print("🔄 Scraping IBPS jobs...")
    jobs = scrape_ibps_jobs()
    save_ibps_csv(jobs)
    print("✓ IBPS scraper complete")
