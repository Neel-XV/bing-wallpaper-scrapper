import argparse
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.firefox.service import Service
from webdriver_manager.firefox import GeckoDriverManager
import requests
import os
from time import sleep
import logging

class BingWallpaperScraper:
    def __init__(self, download_dir="wallpapers"):
        self.download_dir = download_dir
        if not os.path.exists(download_dir):
            os.makedirs(download_dir)
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)
        
        self.options = webdriver.FirefoxOptions()
        self.options.add_argument('--headless')
        self.options.add_argument('--disable-gpu')
        self.options.set_preference('browser.download.folderList', 2)
        self.options.set_preference('browser.download.dir', os.path.abspath(download_dir))
        self.options.set_preference('browser.helperApps.neverAsk.saveToDisk', 'image/jpeg,image/png')
        
    def setup_driver(self):
        try:
            service = Service(GeckoDriverManager().install())
            driver = webdriver.Firefox(service=service, options=self.options)
            driver.set_page_load_timeout(30)
            return driver
        except Exception as e:
            self.logger.error(f"Failed to initialize Firefox WebDriver: {str(e)}")
            raise
    
    def wait_and_find_element(self, driver, by, value, timeout=20, description="element"):
        """Helper method to wait for and find an element"""
        try:
            element = WebDriverWait(driver, timeout).until(
                EC.presence_of_element_located((by, value))
            )
            self.logger.info(f"Found {description}")
            return element
        except TimeoutException:
            self.logger.error(f"Timeout waiting for {description}")
            return None
    
    def wait_and_find_elements(self, driver, by, value, timeout=20, description="elements"):
        """Helper method to wait for and find multiple elements"""
        try:
            elements = WebDriverWait(driver, timeout).until(
                EC.presence_of_all_elements_located((by, value))
            )
            self.logger.info(f"Found {len(elements)} {description}")
            return elements
        except TimeoutException:
            self.logger.error(f"Timeout waiting for {description}")
            return []

    def get_image_urls(self, archive_url):
        self.logger.info(f"Starting to scrape images from {archive_url}")
        driver = None
        image_data = []
        
        try:
            driver = self.setup_driver()
            self.logger.info("Firefox WebDriver initialized successfully")
            
            # Load the archive page
            self.logger.info(f"Loading {archive_url}")
            driver.get(archive_url)
            sleep(5)  # Allow time for JavaScript to execute
            
            # Try different selectors to find the image grid
            selectors = [
                (".grid", "grid container"),
                (".list-bing", "image list"),
                ("//div[contains(@class, 'grid')]", "grid div"),
                ("//div[contains(@class, 'list-bing')]", "list div")
            ]
            
            thumbnails = []
            for selector, description in selectors:
                try:
                    if selector.startswith("//"):
                        elements = driver.find_elements(By.XPATH, selector)
                    else:
                        elements = driver.find_elements(By.CSS_SELECTOR, selector)
                    if elements:
                        self.logger.info(f"Found {description} using {selector}")
                        # Try to find links within this container
                        for element in elements:
                            links = element.find_elements(By.TAG_NAME, "a")
                            if links:
                                thumbnails.extend(links)
                                break
                except Exception as e:
                    self.logger.warning(f"Failed to find elements with {selector}: {str(e)}")
            
            if not thumbnails:
                # Try direct link search
                thumbnails = driver.find_elements(By.CSS_SELECTOR, "a[href*='detail']")
                if not thumbnails:
                    thumbnails = driver.find_elements(By.CSS_SELECTOR, "a[href*='wallpaper']")
            
            self.logger.info(f"Found {len(thumbnails)} potential thumbnail links")
            
            # Print page source for debugging
            with open("page_source.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            self.logger.info("Saved page source to page_source.html for debugging")
            
            for index, thumbnail in enumerate(thumbnails, 1):
                try:
                    image_page_url = thumbnail.get_attribute('href')
                    if not image_page_url:
                        continue
                        
                    self.logger.info(f"Processing thumbnail {index}/{len(thumbnails)}: {image_page_url}")
                    
                    # Open in new tab
                    driver.execute_script(f"window.open('{image_page_url}', '_blank')")
                    driver.switch_to.window(driver.window_handles[-1])
                    sleep(3)  # Wait for page load
                    
                    # Try different selectors for download link
                    download_selectors = [
                        ("a[download]", "download attribute"),
                        ("a[href*='original']", "original image"),
                        ("a[href*='UHD']", "UHD image"),
                        ("//a[contains(@href, '.jpg')]", "jpg link"),
                        ("//a[contains(@href, '.png')]", "png link")
                    ]
                    
                    download_link = None
                    for selector, desc in download_selectors:
                        try:
                            if selector.startswith("//"):
                                elements = driver.find_elements(By.XPATH, selector)
                            else:
                                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                            if elements:
                                download_link = elements[0]
                                self.logger.info(f"Found download link using {desc}")
                                break
                        except Exception:
                            continue
                    
                    if download_link:
                        image_url = download_link.get_attribute('href')
                        image_name = os.path.basename(image_url)
                        image_data.append((image_name, image_url))
                        self.logger.info(f"Successfully processed image: {image_name}")
                    
                    driver.close()
                    driver.switch_to.window(driver.window_handles[0])
                    sleep(2)
                    
                except Exception as e:
                    self.logger.error(f"Error processing thumbnail {index}: {str(e)}")
                    if len(driver.window_handles) > 1:
                        driver.close()
                        driver.switch_to.window(driver.window_handles[0])
                    continue
                
        except Exception as e:
            self.logger.error(f"Error during scraping: {str(e)}")
        finally:
            if driver:
                try:
                    driver.quit()
                    self.logger.info("WebDriver closed successfully")
                except Exception as e:
                    self.logger.error(f"Error closing WebDriver: {str(e)}")
        
        return image_data
    
    def download_images(self, image_data):
        self.logger.info(f"Starting download of {len(image_data)} images")
        
        for index, (image_name, image_url) in enumerate(image_data, 1):
            try:
                output_path = os.path.join(self.download_dir, image_name)
                
                if os.path.exists(output_path):
                    self.logger.info(f"Skipping {image_name} - already exists")
                    continue
                
                self.logger.info(f"Downloading {index}/{len(image_data)}: {image_name}")
                response = requests.get(image_url, stream=True, timeout=30)
                response.raise_for_status()
                
                with open(output_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                
                self.logger.info(f"Successfully downloaded {image_name}")
                sleep(1)
                
            except Exception as e:
                self.logger.error(f"Error downloading {image_name}: {str(e)}")
                continue

def main():
    # Set up argument parser
    parser = argparse.ArgumentParser(description='Bing Wallpaper Scraper')
    parser.add_argument('-m', '--month', default='202410', 
                        help='Month to scrape wallpapers from (format: YYYYMM, default: 202410)')
    
    # Parse arguments
    args = parser.parse_args()
    
    # Construct archive URL based on the month argument
    archive_url = f"https://bingwallpaper.anerg.com/archive/us/{args.month}"
    
    try:
        scraper = BingWallpaperScraper(download_dir="bing_wallpapers")
        
        image_data = scraper.get_image_urls(archive_url)
        
        if image_data:
            scraper.download_images(image_data)
        else:
            logging.error("No image URLs were found to download")
            
    except Exception as e:
        logging.error(f"Main execution failed: {str(e)}")

if __name__ == "__main__":
    main()