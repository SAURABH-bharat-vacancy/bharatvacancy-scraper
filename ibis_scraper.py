import requests
from bs4 import BeautifulSoup
import csv
import re
from datetime import datetime

def scrape_ibps_jobs():
    """Scrape IBPS recruitment notifications"""
    
    jobs = []
    
    try:
        # Main IBPS notifications page
        main_url = "https://ibpsonline.ibps.in/"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        response = requests.get(main_url, headers=headers, timeout=15)
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Find all notification/news items
        # IBPS typically uses divs or sections with notification content
        notification_elements = soup.find_all(['div', 'section', 'article'], 
                                             class_=re.compile(r'news|notification|update|recruitment', re.I))
        
        # Also look for links that contain recruitment keywords
        all_links = soup.find_all('a', href=True)
        
        for link in all_links:
            text = link.get_text(strip=True)
            href = link.get('href', '')
            
            # Check if link is about recruitment/notification
            if any(keyword in text.lower() for keyword in ['recruitment', 'notification', 'notification', 'cwe', 'po', 'clerk', 'officer']):
                
                if not href.startswith('http'):
                    href = main_url.rstrip('/') + '/' + href.lstrip('/')
                
                # Extract job category from text
                category = 'Banking'
                job_type = 'Permanent'
                
                if 'po' in text.lower():
                    title = 'IBPS PO (Probationary Officer)'
                elif 'clerk' in text.lower():
                    title = 'IBPS Clerk'
                elif 'specialist' in text.lower() or 'so' in text.lower():
                    title = 'IBPS Specialist Officer'
                elif 'rrb' in text.lower():
                    if 'clerk' in text.lower():
                        title = 'IBPS RRB Clerk'
                    else:
                        title = 'IBPS RRB Officer'
                else:
                    title = text[:80]
                
                job = {
                    'title': title,
                    'company': 'IBPS',
                    'location': 'All India',
                    'category': category,
                    'job_type': job_type,
                    'application_link': href,
                    'description': text[:200]
                }
                
                # Avoid duplicates
                if not any(j['title'] == job['title'] for j in jobs):
                    jobs.append(job)
        
        # If we found some jobs, great! Otherwise add defaults
        if not jobs:
            print("⚠️  No IBPS jobs found via scraping, adding defaults...")
            jobs = get_default_ibps_jobs()
        
        print(f"✓ Found {len(jobs)} IBPS job notifications")
        return jobs
    
    except requests.exceptions.Timeout:
        print("✗ IBPS request timeout, using defaults...")
        return get_default_ibps_jobs()
    except Exception as e:
        print(f"✗ Error scraping IBPS: {str(e)}")
        return get_default_ibps_jobs()


def get_default_ibps_jobs():
    """Return default IBPS jobs if scraping fails"""
    return [
        {
            'title': 'IBPS PO (Probationary Officer) Recruitment',
            'company': 'IBPS',
            'location': 'All India',
            'category': 'Banking',
            'job_type': 'Permanent',
            'application_link': 'https://ibpsonline.ibps.in/cwepo2025/',
            'description': 'Apply for IBPS Probationary Officer positions in nationalised banks'
        },
        {
            'title': 'IBPS Clerk Recruitment',
            'company': 'IBPS',
            'location': 'All India',
            'category': 'Banking',
            'job_type': 'Permanent',
            'application_link': 'https://ibpsonline.ibps.in/cweclk2025/',
            'description': 'IBPS Clerk recruitment for public sector banks'
        },
        {
            'title': 'IBPS Specialist Officer Recruitment',
            'company': 'IBPS',
            'location': 'All India',
            'category': 'Banking',
            'job_type': 'Permanent',
            'application_link': 'https://ibpsonline.ibps.in/cweso/',
            'description': 'Specialist Officer positions in IT, HR, and other departments'
        },
        {
            'title': 'IBPS RRB Officer Scale-I',
            'company': 'IBPS',
            'location': 'All India',
            'category': 'Banking',
            'job_type': 'Permanent',
            'application_link': 'https://ibpsonline.ibps.in/crrbco/',
            'description': 'Regional Rural Bank Officer recruitment'
        }
    ]


def save_ibps_csv(jobs):
    """Save IBPS jobs to CSV in WordPress format"""
    
    if not jobs:
        print("No jobs to save")
        return
    
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
    print("✅ IBPS scraper complete")
