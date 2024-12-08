import argparse
import concurrent.futures
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.firefox.service import Service
from webdriver_manager.firefox import GeckoDriverManager
import requests
import os
from time import sleep
import logging
import urllib3

# Suppress warnings to reduce log noise
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class BingWallpaperScraper:
    def __init__(self, download_dir="images", max_workers=10):
        self.download_dir = download_dir
        self.max_workers = max_workers

        # Create download directory if it doesn't exist
        if not os.path.exists(download_dir):
            os.makedirs(download_dir)

        # Configure logging
        logging.basicConfig(
            level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
        )
        self.logger = logging.getLogger(__name__)

        # Firefox WebDriver options
        self.options = webdriver.FirefoxOptions()
        self.options.add_argument("--headless")
        self.options.add_argument("--disable-gpu")
        self.options.add_argument("--no-sandbox")
        self.options.set_preference("browser.download.folderList", 2)
        self.options.set_preference(
            "browser.download.dir", os.path.abspath(download_dir)
        )
        self.options.set_preference(
            "browser.helperApps.neverAsk.saveToDisk", "image/jpeg,image/png"
        )

    def setup_driver(self):
        """Set up and return a configured Firefox WebDriver."""
        try:
            service = Service(GeckoDriverManager().install())
            driver = webdriver.Firefox(service=service, options=self.options)
            driver.set_page_load_timeout(30)
            driver.set_script_timeout(30)
            return driver
        except Exception as e:
            self.logger.error(f"Failed to initialize Firefox WebDriver: {str(e)}")
            raise

    def get_image_urls(self, archive_url):
        """
        Scrape image URLs from the given archive URL.

        :param archive_url: URL of the Bing wallpaper archive
        :return: List of tuples (image_name, image_url)
        """
        self.logger.info(f"Starting to scrape images from {archive_url}")
        driver = None
        image_data = []

        try:
            driver = self.setup_driver()
            self.logger.info("Firefox WebDriver initialized successfully")

            # Load the archive page with explicit wait
            self.logger.info(f"Loading {archive_url}")
            driver.get(archive_url)

            # More efficient wait strategy
            wait = WebDriverWait(driver, 15)

            # Prioritized selectors for finding thumbnail links
            selectors = [
                (By.CSS_SELECTOR, "div.grid a[href*='detail']"),
                (By.CSS_SELECTOR, "a[href*='detail']"),
                (By.XPATH, "//a[contains(@href, '/detail/')]"),
            ]

            thumbnails = []
            for by, selector in selectors:
                try:
                    thumbnails = wait.until(
                        EC.presence_of_all_elements_located((by, selector))
                    )
                    if thumbnails:
                        self.logger.info(
                            f"Found {len(thumbnails)} thumbnail links using {selector}"
                        )
                        break
                except TimeoutException:
                    continue

            if not thumbnails:
                self.logger.warning("No thumbnail links found")
                return []

            # Process thumbnails with more efficient approach
            for index, thumbnail in enumerate(thumbnails, 1):
                try:
                    image_page_url = thumbnail.get_attribute("href")
                    if not image_page_url:
                        continue

                    self.logger.info(
                        f"Processing thumbnail {index}/{len(thumbnails)}: {image_page_url}"
                    )

                    # Open new tab and switch
                    driver.execute_script(f"window.open('{image_page_url}', '_blank')")
                    driver.switch_to.window(driver.window_handles[-1])

                    # Wait for page load with more aggressive timeout
                    wait = WebDriverWait(driver, 10)

                    # More comprehensive download link selectors
                    download_selectors = [
                        (By.CSS_SELECTOR, "a[download]"),
                        (By.CSS_SELECTOR, "a[href*='original']"),
                        (By.CSS_SELECTOR, "a[href*='UHD']"),
                        (By.XPATH, "//a[contains(@href, '.jpg')]"),
                        (By.XPATH, "//a[contains(@href, '.png')]"),
                    ]

                    download_link = None
                    for by, selector in download_selectors:
                        try:
                            download_link = wait.until(
                                EC.presence_of_element_located((by, selector))
                            )
                            self.logger.info(f"Found download link using {selector}")
                            break
                        except TimeoutException:
                            continue

                    if download_link:
                        image_url = download_link.get_attribute("href")

                        # Extract filename from image page URL
                        clean_image_name = (
                            os.path.basename(image_page_url)
                            .replace("/", "_")
                            .replace(":", "_")
                        )
                        image_ext = (
                            os.path.splitext(os.path.basename(image_url))[1] or ".jpg"
                        )
                        full_image_name = f"{clean_image_name}{image_ext}"

                        image_data.append((full_image_name, image_url))
                        self.logger.info(
                            f"Successfully processed image: {full_image_name}"
                        )

                    driver.close()
                    driver.switch_to.window(driver.window_handles[0])

                except Exception as e:
                    self.logger.error(f"Error processing thumbnail {index}: {str(e)}")
                    # Ensure we always switch back to the main window
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

    def download_image_with_retry(self, image_data, month, max_retries=3):
        """
        Download a single image with retry mechanism

        :param image_data: Tuple of (image_name, image_url)
        :param month: Month to create subdirectory
        :param max_retries: Maximum number of download retries
        :return: Tuple of (success, image_name)
        """
        image_name, image_url = image_data

        # Create month-specific subdirectory
        month_dir = os.path.join(self.download_dir, month)
        os.makedirs(month_dir, exist_ok=True)

        output_path = os.path.join(month_dir, image_name)

        for attempt in range(max_retries):
            try:
                # Check if file already exists
                if os.path.exists(output_path):
                    self.logger.info(f"Skipping {image_name} - already exists")
                    return True, image_name

                self.logger.info(f"Downloading attempt {attempt + 1}: {image_name}")

                # Use a longer timeout and stream the download
                response = requests.get(
                    image_url,
                    stream=True,
                    timeout=(10, 30),  # (connect timeout, read timeout)
                    verify=False,  # Disable SSL verification to prevent connection issues
                )
                response.raise_for_status()

                with open(output_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)

                self.logger.info(f"Successfully downloaded {image_name}")
                return True, image_name

            except Exception as e:
                self.logger.warning(
                    f"Download attempt {attempt + 1} failed for {image_name}: {str(e)}"
                )
                sleep(2)  # Wait before retry

        self.logger.error(
            f"Failed to download {image_name} after {max_retries} attempts"
        )
        return False, image_name

    def download_images(self, image_data, month):
        """
        Download images in parallel

        :param image_data: List of (image_name, image_url) tuples
        :param month: Month to create subdirectory
        """
        self.logger.info(f"Starting parallel download of {len(image_data)} images")

        # Use ThreadPoolExecutor for parallel downloads
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self.max_workers
        ) as executor:
            # Create download tasks
            download_futures = {
                executor.submit(self.download_image_with_retry, img, month): img
                for img in image_data
            }

            # Process results as they complete
            for future in concurrent.futures.as_completed(download_futures):
                success, image_name = future.result()
                if not success:
                    self.logger.error(f"Failed to download {image_name}")


def main():
    # Set up argument parser
    parser = argparse.ArgumentParser(description="Bing Wallpaper Scraper")
    parser.add_argument(
        "-m",
        "--month",
        default="202410",
        help="Month to scrape wallpapers from (format: YYYYMM, default: 202410)",
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=10,
        help="Number of concurrent download workers (default: 10)",
    )

    # Parse arguments
    args = parser.parse_args()

    # Construct archive URL based on the month argument
    archive_url = f"https://bingwallpaper.anerg.com/archive/us/{args.month}"

    try:
        # Initialize scraper with custom number of workers
        # Note: download_dir is now set to 'images' by default
        scraper = BingWallpaperScraper(max_workers=args.workers)

        # Scrape image URLs
        image_data = scraper.get_image_urls(archive_url)

        # Download images if any were found
        if image_data:
            scraper.download_images(image_data, args.month)
        else:
            logging.error("No image URLs were found to download")

    except Exception as e:
        logging.error(f"Main execution failed: {str(e)}")


if __name__ == "__main__":
    main()
