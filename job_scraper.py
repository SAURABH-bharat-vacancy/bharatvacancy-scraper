#!/usr/bin/env python3
import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime
import os

WEBSITES = {
    'SSC': {'url': 'https://ssc.gov.in', 'category': 'SSC Jobs', 'location': 'All India'},
    'IBPS': {'url': 'https://ibps.in', 'category': 'Banking Jobs', 'location': 'All India'},
    'SBI': {'url': 'https://sbi.co.in', 'category': 'Banking Jobs', 'location': 'All India'},
    'RRB': {'url': 'https://rrbcdg.gov.in', 'category': 'Railways Jobs', 'location': 'All India'},
    'NDA': {'url': 'https://nda.ac.in', 'category': 'Defence Jobs', 'location': 'All India'}
}

class JobScraper:
    def __init__(self):
        self.jobs = []
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
    
    def scrape_sources(self):
        print("Starting Data Scraper Engine...")
        for source, config in WEBSITES.items():
            try:
                res = requests.get(config['url'], headers=self.headers, timeout=15)
                soup = BeautifulSoup(res.content, 'html.parser')
                links = soup.find_all('a', limit=60)
                found = False
                
                for link in links:
                    title = link.get_text().strip()
                    href = link.get('href', '')
                    if len(title) > 12 and any(k in title.lower() for k in ['notice', 'job', 'vacancy', 'apply', 'recruitment']):
                        if href.startswith('/'): 
                            href = config['url'].split('//') + '//' + config['url'].split('//') + href
                        
                        self.jobs.append({
                            'title': title[:150],
                            'url': href,
                            'source': source,
                            'category': config['category'],
                            'location': config['location'],
                            'posted_date': datetime.now().strftime('%Y-%m-%d')
                        })
                        found = True
                        break
                
                if not found:
                    self.jobs.append({
                        'title': f"Latest {source} Recruitment Notifications & Open Vacancies",
                        'url': config['url'], 'source': source, 'category': config['category'], 'location': config['location'], 'posted_date': datetime.now().strftime('%Y-%m-%d')
                    })
            except Exception as e:
                print(f"Error reading {source}: {e}")
                self.jobs.append({
                    'title': f"Check Latest {source} Vacancies Directly",
                    'url': config['url'], 'source': source, 'category': config['category'], 'location': config['location'], 'posted_date': datetime.now().strftime('%Y-%m-%d')
                })
                
    def post_to_wordpress(self):
        # We target the custom tracking parameters endpoint to bypass raw root POST blocks
        wp_url = "https://bharatvacancy.com"
        wp_user = os.environ.get('WP_USER')
        wp_pass = os.environ.get('WP_APP_PASS')
        
        if not wp_user or not wp_pass:
            print("Configuration Error: Secrets are missing from GitHub Settings.")
            return

        print("\n📤 Syncing with WordPress database via Form Parameter authentication...")
        
        # Base headers to bypass simple browser filters
        request_headers = {
            'User-Agent': self.headers['User-Agent']
        }

        for job in self.jobs:
            # Check for duplicates using parameter queries rather than token requests
            check_url = f"{wp_url}?search={requests.utils.quote(job['title'][:20])}"
            try:
                check_res = requests.get(check_url, headers=request_headers, timeout=10)
                if check_res.status_code == 200 and len(check_res.json()) > 0:
                    print(f" ⏭️ Already Posted: {job['title'][:40]}...")
                    continue
            except: pass

            content_html = f"""
            <p><strong>Department/Source:</strong> {job['source']}</p>
            <p><strong>Job Location:</strong> {job['location']}</p>
            <p><strong>Category:</strong> {job['category']}</p>
            <p><strong>Notification Date:</strong> {job['posted_date']}</p>
            <hr style='border: 0; height: 1px; background: #eee; margin: 20px 0;'>
            <p><a href='{job['url']}' target='_blank' style='background:#0073aa;color:#fff;padding:12px 24px;text-decoration:none;border-radius:4px;display:inline-block;font-weight:bold;'>Click Here to Apply & View Details</a></p>
            """
            
            # Pass authorization explicitly inside the payload body matrix
            payload = {
                'title': job['title'],
                'content': content_html,
                'status': 'publish',
                'username': wp_user,
                'password': wp_pass
            }
            
            try:
                # We use standard form data processing here
                res = requests.post(wp_url, headers=request_headers, data=payload, timeout=15)
                if res.status_code == 201:
                    print(f"  ✓ Live Published: {job['title'][:40]}...")
                else:
                    print(f"  ✗ Failed to post ({res.status_code}): {job['title'][:40]}")
            except Exception as e:
                print(f"  ✗ Error: {e}")

    def save_to_json(self, filename='jobs_data.json'):
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(self.jobs, f, ensure_ascii=False, indent=2)

def main():
    scraper = JobScraper()
    scraper.scrape_sources()
    scraper.save_to_json()
    scraper.post_to_wordpress()

if __name__ == '__main__':
    main()
