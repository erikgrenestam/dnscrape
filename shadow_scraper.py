'''
Updated scraper script to handle shadow DOM elements on nationalbanken.dk
'''
import os
import json
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import time

# Selenium imports
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options as ChromeOptions
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

BASE_URL = "https://www.nationalbanken.dk"
START_URL = "https://www.nationalbanken.dk/da/soeg-i-vidensarkivet"
DOCS_DIR = "docs"
METADATA_FILE = "docs_metadata.json"

# Global WebDriver instance
_driver = None

def init_selenium_driver():
    global _driver
    if _driver is None:
        print("Initializing Selenium WebDriver...")
        chrome_options = ChromeOptions()
        #chrome_options.add_argument("--headless")  # Run headless
        #chrome_options.add_argument("--disable-gpu")
        #chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument('--disable-notifications')
        chrome_options.add_argument("--window-size=1920,1080") # Standard window size
        chrome_options.add_argument("--start-maximized") # Make window maximized
        #chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
        chrome_options.add_experimental_option("detach", True) # Keep browser open for debugging
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"]) # Make it less obvious it's automated
        try:
            # Initialize ChromeDriverManager
            chrome_driver_path = ChromeDriverManager().install()
            service = ChromeService(chrome_driver_path)
            _driver = webdriver.Chrome(service=service, options=chrome_options)
            _driver.set_window_position(0, 0) # Position window at top-left
            print("Selenium WebDriver initialized successfully.")
        except Exception as e:
            print(f"Error initializing Selenium WebDriver: {e}")
            print("Please ensure Chrome is installed and accessible.")
            _driver = None # Ensure it's None if init fails
    return _driver

def close_selenium_driver():
    global _driver
    if (_driver):
        print("Closing Selenium WebDriver...")
        _driver.quit()
        _driver = None
        print("Selenium WebDriver closed.")

def find_in_shadow_root(driver, host_css_selector, shadow_css_selector):
    '''Find element within a shadow root using JavaScript execution.'''
    try:
        print(f"Looking for element in shadow root: {host_css_selector} -> {shadow_css_selector}")
        script = f"""
            var host = document.querySelector("{host_css_selector}");
            if (!host) return null;
            var shadowRoot = host.shadowRoot;
            if (!shadowRoot) return null;
            return shadowRoot.querySelector("{shadow_css_selector}");
        """
        element = driver.execute_script(script)
        if element:
            print(f"Found element in shadow root: {shadow_css_selector}")
        return element
    except Exception as e:
        print(f"Error finding element in shadow root: {e}")
        return None

def find_elements_in_all_shadow_roots(driver, shadow_css_selector):
    '''Find elements in all shadow roots recursively using JavaScript.'''
    try:
        print(f"Looking for elements in all shadow roots with selector: {shadow_css_selector}")
        script = f"""
            // Search all shadow roots recursively
            function findElementsInAllShadows(rootNode, selector) {{
                let results = [];
                
                // Check all elements for shadow roots
                const elements = rootNode.querySelectorAll('*');
                for (const el of elements) {{
                    if (el.shadowRoot) {{
                        // Search in this shadow root
                        const found = el.shadowRoot.querySelectorAll(selector);
                        if (found.length) {{
                            console.log('Found ' + found.length + ' in shadow root of:', el.tagName);
                            results = results.concat(Array.from(found));
                        }}
                        
                        // Also search nested shadow roots
                        const nestedFound = findElementsInAllShadows(el.shadowRoot, selector);
                        if (nestedFound.length) {{
                            results = results.concat(nestedFound);
                        }}
                    }}
                }}
                
                return results;
            }}
            
            return findElementsInAllShadows(document, "{shadow_css_selector}");
        """
        elements = driver.execute_script(script)
        print(f"Found {len(elements)} elements in all shadow roots with selector: {shadow_css_selector}")
        return elements
    except Exception as e:
        print(f"Error finding elements in shadow roots: {e}")
        return []

def accept_cookies(driver):
    '''Accepts cookies by clicking the "Allow all cookies" button if it's present.
    Handles both normal DOM and shadow DOM elements.'''
    try:
        print("Looking for cookie consent dialog...")
        
        # First check regular DOM
        try:
            # Wait for regular cookie dialog (shorter timeout)
            cookie_button = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.ID, "CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll"))
            )
            print("Cookie dialog found in regular DOM. Accepting cookies...")
            
            # Take screenshot before clicking
            driver.get_screenshot_as_file("before_cookie_click.png")
            
            # Try JavaScript click for reliability
            driver.execute_script("arguments[0].click();", cookie_button)
            print("Cookie accept button clicked.")
            
        except Exception as dom_error:
            print(f"Cookie dialog not found in regular DOM: {dom_error}")
            print("Checking for cookie dialog in shadow DOM...")
            
            # Try to find the button in shadow DOM
            # Common shadow root hosts that might contain cookie dialogs
            shadow_hosts = [
                "cybotCookiebotRoot",
                "div#CybotCookiebotDialog",
                "div.cookie-dialog",
                "div.cookie-consent",
                "dnb-cookie-consent",
                "#cookie-consent",
                "body > div:first-child"
            ]
            
            found_in_shadow = False
            for host in shadow_hosts:
                # Try multiple possible button selectors within shadow root
                shadow_button_selectors = [
                    "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll", 
                    "button.accept-all", 
                    "button.accept", 
                    "[id*='allow-all']", 
                    "[id*='accept-all']"
                ]
                
                for selector in shadow_button_selectors:
                    cookie_button = find_in_shadow_root(driver, host, selector)
                    if cookie_button:
                        print(f"Found cookie button in shadow root: {host} -> {selector}")
                        driver.execute_script("arguments[0].click();", cookie_button)
                        print("Cookie button in shadow DOM clicked.")
                        found_in_shadow = True
                        break
                
                if found_in_shadow:
                    break
            
            if not found_in_shadow:
                # Last resort - use direct JavaScript to look for and click common cookie buttons
                print("Trying direct JavaScript approach to accept cookies...")
                script = """
                    // Common cookie accept button patterns
                    const buttonSelectors = [
                        '#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll',
                        'button[id*="accept-all"]', 
                        'button[id*="acceptAll"]',
                        'button.accept-all',
                        'button.acceptAll',
                        'button.accept_all',
                        'a[id*="accept-all"]'
                    ];
                    
                    // Try to find and click the button
                    for (const selector of buttonSelectors) {
                        const elements = document.querySelectorAll(selector);
                        for (const el of elements) {
                            if (el && el.offsetParent !== null) {  // Check if visible
                                console.log('Found cookie button:', selector);
                                el.click();
                                return true;
                            }
                        }
                    }
                    
                    // Look for buttons in all shadow roots
                    function searchShadowRoots(root) {
                        const elements = root.querySelectorAll('*');
                        for (const el of elements) {
                            if (el.shadowRoot) {
                                for (const selector of buttonSelectors) {
                                    const shadowButton = el.shadowRoot.querySelector(selector);
                                    if (shadowButton) {
                                        shadowButton.click();
                                        return true;
                                    }
                                }
                                if (searchShadowRoots(el.shadowRoot)) return true;
                            }
                        }
                        return false;
                    }
                    
                    return searchShadowRoots(document);
                """
                clicked = driver.execute_script(script)
                if clicked:
                    print("Successfully clicked cookie button using JavaScript.")
                    found_in_shadow = True
        
        # Take a screenshot after clicking
        driver.get_screenshot_as_file("after_cookie_click.png")
        
        # Wait for dialog to disappear and page to stabilize
        time.sleep(5)
        return True
    
    except Exception as e:
        print(f"Error during cookie acceptance process: {e}")
        print("Continuing without accepting cookies.")
        return False

def extract_attributes_from_shadow_element(driver, element):
    '''Extract all attributes from a shadow DOM element'''
    try:
        attrs = driver.execute_script("""
            const attrs = {};
            for (const attr of arguments[0].attributes) {
                attrs[attr.name] = attr.value;
            }
            return attrs;
        """, element)
        return attrs
    except Exception as e:
        print(f"Error extracting attributes: {e}")
        return {}

def download_pdf(pdf_url, filename):
    '''Downloads a PDF from a URL to a local file.'''
    if not os.path.exists(DOCS_DIR):
        os.makedirs(DOCS_DIR)
        
    safe_filename = "".join(c if c.isalnum() or c in ('.', '_', '-') else '_' for c in os.path.basename(filename))
    filepath = os.path.join(DOCS_DIR, safe_filename)
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(pdf_url, stream=True, timeout=30, headers=headers)
        response.raise_for_status()
        with open(filepath, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        print(f"Downloaded {safe_filename}")
        return True
    except requests.exceptions.RequestException as e:
        print(f"Error downloading {pdf_url}: {e}")
        return False
    except IOError as e:
        print(f"Error writing file {filepath}: {e}")
        return False

def analyze_shadow_dom_structure(driver):
    '''Analyze the shadow DOM structure of the current page and print useful information'''
    print("\nAnalyzing shadow DOM structure of current page...")
    
    # Execute JavaScript to recursively inspect all shadow roots and return useful information
    structure = driver.execute_script("""
        // Track all shadow DOM roots
        const shadowRoots = [];
        
        // Find all shadow roots in the document
        function findShadowRoots(node, path) {
            if (!node) return;
            
            if (node.querySelectorAll) {
                const elements = node.querySelectorAll('*');
                for (const el of elements) {
                    if (el.shadowRoot) {
                        const nodePath = path + ' > ' + (el.tagName || 'unknown').toLowerCase() + 
                            (el.id ? '#' + el.id : '') + 
                            (el.className && typeof el.className === 'string' ? '.' + el.className.replace(/\s+/g, '.') : '');
                        
                        // Gather info about this shadow root
                        const info = {
                            hostTagName: el.tagName,
                            hostId: el.id || null,
                            hostClass: el.className || null,
                            path: nodePath,
                            childElements: {}
                        };
                        
                        // Look for interesting elements inside this shadow root
                        const links = el.shadowRoot.querySelectorAll('a');
                        if (links.length) {
                            info.links = Array.from(links).slice(0, 5).map(a => ({
                                href: a.href || null,
                                text: a.textContent || null,
                                download: a.hasAttribute('download'),
                                class: a.className || null
                            }));
                        }
                        
                        // Count element types in this shadow root
                        Array.from(el.shadowRoot.querySelectorAll('*')).forEach(child => {
                            const tag = child.tagName.toLowerCase();
                            info.childElements[tag] = (info.childElements[tag] || 0) + 1;
                        });
                        
                        shadowRoots.push(info);
                        
                        // Recursively check for nested shadow roots
                        findShadowRoots(el.shadowRoot, nodePath);
                    }
                }
            }
        }
        
        findShadowRoots(document, 'document');
        
        // Also specifically look for PDF links in all shadow roots
        const pdfLinks = [];
        
        function findPdfLinksInShadows(rootNode) {
            if (!rootNode || !rootNode.querySelectorAll) return;
            
            // Check all elements for shadow roots
            const elements = rootNode.querySelectorAll('*');
            for (const el of elements) {
                if (el.shadowRoot) {
                    // Look for links in this shadow root
                    const links = el.shadowRoot.querySelectorAll('a');
                    for (const link of links) {
                        const href = link.href || link.getAttribute('href') || '';
                        if (href.toLowerCase().endsWith('.pdf') || link.hasAttribute('download')) {
                            pdfLinks.push({
                                href: href,
                                text: link.textContent || null,
                                hasDownload: link.hasAttribute('download'),
                                class: link.className || null,
                                hostTag: el.tagName.toLowerCase(),
                                hostPath: el.id ? '#' + el.id : el.className ? '.' + el.className.replace(/\s+/g, '.') : el.tagName.toLowerCase()
                            });
                        }
                    }
                    
                    // Recursively check nested shadow roots
                    findPdfLinksInShadows(el.shadowRoot);
                }
            }
        }
        
        findPdfLinksInShadows(document);
        
        return {
            shadowRoots: shadowRoots,
            pdfLinks: pdfLinks,
            totalShadowRoots: shadowRoots.length
        };
    """)
    
    print(f"\nFound {structure.get('totalShadowRoots', 0)} shadow roots on page")
    
    # Print PDF links specifically
    pdf_links = structure.get('pdfLinks', [])
    print(f"Found {len(pdf_links)} potential PDF links in shadow DOM:")
    for i, link in enumerate(pdf_links[:5]):  # Show first 5 only
        print(f"  Link {i+1}:")
        print(f"    href: {link.get('href', 'N/A')}")
        print(f"    text: {link.get('text', 'N/A')}")
        print(f"    download attr: {link.get('hasDownload', False)}")
        print(f"    class: {link.get('class', 'N/A')}")
        print(f"    host: {link.get('hostTag', 'N/A')} ({link.get('hostPath', 'N/A')})")
    
    # Print some shadow roots
    shadow_roots = structure.get('shadowRoots', [])
    print(f"\nShowing details for first few shadow roots:")
    for i, root in enumerate(shadow_roots[:3]):  # Show first 3 only
        print(f"  Root {i+1}: {root.get('hostTagName', 'unknown')} - {root.get('path', 'unknown path')}")
        print(f"    Child elements: {root.get('childElements', {})}")
        if 'links' in root:
            print(f"    Contains {len(root['links'])} links")
            
    return structure

def extract_pdf_links_from_shadow_dom(driver):
    '''Extract all PDF links from shadow DOM using specialized JavaScript.
    Returns a list of dictionaries with href and other properties.'''
    print("Extracting PDF links from shadow DOM with specialized JavaScript...")
    
    script = """
        // Track all PDF links
        const pdfLinks = [];
        
        // Common PDF link patterns
        const PDF_SELECTORS = [
            'a.related-card__link[download]',
            'a.related-card__link[href$=".pdf"]',
            'a[download]',
            'a[href$=".pdf"]',
            'a[href*=".pdf"]',
            'a.download-file',
            'a.pdf-link'
        ];
        
        // Search document and all shadow roots recursively
        function findPdfLinks(node, path) {
            if (!node || !node.querySelectorAll) return;
            
            // Check regular links in this node
            PDF_SELECTORS.forEach(selector => {
                try {
                    const links = node.querySelectorAll(selector);
                    for (const link of links) {
                        const href = link.href || link.getAttribute('href') || '';
                        if (href.toLowerCase().includes('.pdf') || link.hasAttribute('download')) {
                            pdfLinks.push({
                                href: href,
                                text: link.textContent?.trim() || null,
                                hasDownload: link.hasAttribute('download'),
                                class: link.className || null,
                                hostPath: path
                            });
                        }
                    }
                } catch (e) {
                    console.error('Error searching for selector:', selector, e);
                }
            });
            
            // Check for shadow roots
            if (node.querySelectorAll) {
                const elements = node.querySelectorAll('*');
                for (const el of elements) {
                    if (el.shadowRoot) {
                        const nodePath = path + ' > ' + (el.tagName || 'unknown').toLowerCase() + 
                            (el.id ? '#' + el.id : '') + 
                            (el.className && typeof el.className === 'string' ? '.' + el.className.replace(/\s+/g, '.') : '');
                        
                        // Search inside this shadow root
                        findPdfLinks(el.shadowRoot, nodePath);
                    }
                }
            }
        }
        
        // Start searching from the document
        findPdfLinks(document, 'document');
        
        // Look specifically for related card links which might be special components
        document.querySelectorAll('*').forEach(el => {
            if (el.shadowRoot) {
                const relatedCards = el.shadowRoot.querySelectorAll('*[class*="related-card"]');
                if (relatedCards.length) {
                    relatedCards.forEach(card => {
                        // Try to find links inside related cards
                        const links = card.querySelectorAll('a');
                        links.forEach(link => {
                            const href = link.href || link.getAttribute('href') || '';
                            pdfLinks.push({
                                href: href,
                                text: link.textContent?.trim() || null,
                                hasDownload: link.hasAttribute('download'),
                                class: link.className || null,
                                hostPath: 'related-card'
                            });
                        });
                    });
                }
            }
        });
        
        return pdfLinks;
    """
    
    links = driver.execute_script(script)
    print(f"Found {len(links)} potential PDF links in shadow DOM.")
    
    # Filter to keep only actual PDF links
    pdf_links = [link for link in links if link['href'] and 
                ('.pdf' in link['href'].lower() or link.get('hasDownload'))]
    
    print(f"After filtering: {len(pdf_links)} PDF links.")
    return pdf_links

def save_metadata_per_page(metadata, page_num):
    '''Saves the current metadata to a JSON file with page number in the filename'''
    if not metadata:
        print(f"No metadata to save for page {page_num}")
        return
        
    if not os.path.exists(DOCS_DIR):
        os.makedirs(DOCS_DIR)
        
    metadata_filename = os.path.join(DOCS_DIR, f"metadata_page_{page_num}.json")
    
    try:
        with open(metadata_filename, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=4, ensure_ascii=False)
        print(f"Metadata for page {page_num} saved to {metadata_filename}")
    except Exception as e:
        print(f"Error saving metadata for page {page_num}: {e}")

def main():
    if not os.path.exists(DOCS_DIR):
        os.makedirs(DOCS_DIR)

    all_metadata = []
    processed_article_urls = set()
    page_num = 32
    max_pages_to_scrape = 130 # Safety break for testing, adjust as needed
    first_page = True

    try:
        driver = init_selenium_driver()
        if not driver:
            print("Failed to initialize WebDriver. Exiting.")
            return
            
        while True:
            if page_num > max_pages_to_scrape:
                print(f"Reached max page limit ({max_pages_to_scrape}), stopping.")
                break

            current_search_url = f"{START_URL}?page={page_num}" if page_num > 1 else START_URL
            print(f"Processing search page: {current_search_url}")
            
            # Load the search page
            driver.get(current_search_url)
            time.sleep(3)
            
            # Accept cookies if needed
            if page_num == 1 or first_page:
                accept_cookies(driver)
            
            # Find search result items in shadow DOM
            result_items = find_elements_in_all_shadow_roots(driver, "dnb-search-result-item")
            
            if not result_items:
                if page_num == 1:
                    print("No search results found on the first page. Exiting.")
                else:
                    print("No more search results found. End of results.")
                break
            print(f"Found {len(result_items)} search result items on page {page_num}")
            
            # First, extract all article data and URLs from the search page
            page_articles = []
            found_new_articles_on_page = False
            
            # Store the metadata for each page separately
            page_metadata = []
            
            print("Extracting article metadata from search results...")
            for item in result_items:
                # Extract attributes from the shadow DOM element
                attrs = extract_attributes_from_shadow_element(driver, item)
                
                # Get article information
                article_title = attrs.get('header', 'N/A').strip()
                content_type = attrs.get('content-type', '')
                topic = attrs.get('topic', '')
                date = attrs.get('date', '')
                description = attrs.get('description', '')
                
                # Extract URL from link attribute (which is a JSON string)
                link_json_str = attrs.get('link', '{}')
                article_url = None
                
                try:
                    link_data = json.loads(link_json_str)
                    raw_url = link_data.get('url')
                    if (raw_url):
                        article_url = urljoin(BASE_URL, raw_url)
                except json.JSONDecodeError:
                    print(f"  Error decoding link JSON for item '{article_title}': {link_json_str}")
                
                # If no URL found, skip this item
                if not article_url:
                    print(f"  Could not find a valid URL for item: {article_title}")
                    continue
                
                # Skip if already processed
                if article_url in processed_article_urls:
                    print(f"  Skipping already processed article: {article_title}")
                    continue
                
                # Store the article metadata for later processing
                page_articles.append({
                    'url': article_url,
                    'title': article_title,
                    'content_type': content_type,
                    'topic': topic,
                    'date': date,
                    'description': description
                })
                found_new_articles_on_page = True
            
            # Now visit each article URL one by one
            for article in page_articles:
                article_url = article['url']
                article_title = article['title']
                
                processed_article_urls.add(article_url)
                print(f"  Visiting article page: {article_title} ({article_url})")
                # Load the article page
                driver.get(article_url)

                WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.CLASS_NAME, "h2"))
                )
                time.sleep(2)  # Wait for page to load
                
                # Analyze the shadow DOM structure to better understand the page
                shadow_structure = analyze_shadow_dom_structure(driver)
                driver.get_screenshot_as_file(f"article_page_{len(processed_article_urls)}.png")
                
                # First try to use the PDF links we found from our shadow DOM analysis
                pdf_links = []
                pdf_links_from_analysis = shadow_structure.get('pdfLinks', [])
                
                if pdf_links_from_analysis:
                    print(f"    Found {len(pdf_links_from_analysis)} PDF links from shadow DOM analysis")
                    
                    # Convert the analyzed links to objects that can be used like WebElements
                    for link_info in pdf_links_from_analysis:
                        href = link_info.get('href')
                        if href and (href.lower().endswith('.pdf') or link_info.get('hasDownload')):
                            # Create a dictionary that mimics a WebElement with properties we need
                            link_obj = {
                                'href': href,
                                'text': link_info.get('text'),
                                'getAttribute': lambda attr, h=href: h if attr == 'href' else None
                            }
                            pdf_links.append(link_obj)
                
                # If no PDF links found through analysis, try regular DOM
                if not pdf_links:
                    print("    No PDF links found in shadow DOM analysis, trying regular DOM...")
                    regular_pdf_links = driver.find_elements(By.CSS_SELECTOR, "a.related-card__link[download], a[href$='.pdf']")
                    
                    if regular_pdf_links:
                        pdf_links = regular_pdf_links
                    else:
                        # If still nothing found, try our custom shadow DOM search
                        print("    No PDF links found in regular DOM, searching in shadow DOM...")
                        
                        # Try selectors in order of specificity
                        shadow_selectors = [
                            "a.related-card__link[download]",
                            "a.related-card__link[href$='.pdf']",
                            "a[download]", 
                            "a[href$='.pdf']",
                            "a[href*='.pdf']"
                        ]
                        
                        for selector in shadow_selectors:
                            pdf_links_in_shadow = find_elements_in_all_shadow_roots(driver, selector)
                            if pdf_links_in_shadow:
                                pdf_links = pdf_links_in_shadow
                                break
                
                print(f"    Found {len(pdf_links)} potential PDF links")
                  # Process PDF links
                pdf_found_for_article = False
                for pdf_link in pdf_links:
                    try:
                        # Handle both WebElements and our custom dictionary objects
                        pdf_href = None
                        
                        # If it's a dictionary from our shadow DOM analysis
                        if isinstance(pdf_link, dict) and 'href' in pdf_link:
                            pdf_href = pdf_link['href']
                            print(f"    Processing PDF link from shadow analysis: {pdf_href}")
                        # If it's a regular WebElement
                        elif hasattr(pdf_link, 'get_attribute'):
                            pdf_href = pdf_link.get_attribute('href')
                            if not pdf_href:
                                # Try with JavaScript to get href from shadow DOM element
                                pdf_href = driver.execute_script("return arguments[0].href || arguments[0].getAttribute('href');", pdf_link)
                        # If it's something else, try JavaScript as a last resort
                        else:
                            try:
                                pdf_href = driver.execute_script("return arguments[0].href || arguments[0].getAttribute('href');", pdf_link)
                            except:
                                print(f"    Cannot extract href from {type(pdf_link)}")
                        
                        if pdf_href and pdf_href.lower().endswith(".pdf"):
                            full_pdf_url = urljoin(BASE_URL, pdf_href)
                            parsed_pdf_url = urlparse(full_pdf_url)
                            pdf_filename = os.path.basename(parsed_pdf_url.path)
                            
                            if not pdf_filename:
                                print(f"    Could not determine filename for PDF: {full_pdf_url}")
                                continue
                            print(f"    Found PDF: {full_pdf_url}")
                            if download_pdf(full_pdf_url, pdf_filename):
                                metadata = {
                                    "source_page_url": article_url,
                                    "pdf_url": full_pdf_url,
                                    "downloaded_filename": pdf_filename,
                                    "title": article['title'],
                                    "date": article['date'],
                                    "content_type": article['content_type'],
                                    "topic": article['topic'],
                                    "description": article['description']
                                }
                                all_metadata.append(metadata)
                                page_metadata.append(metadata)
                                pdf_found_for_article = True
                            else:
                                print(f"    Failed to download {pdf_filename}")
                    except Exception as e:
                        print(f"    Error processing PDF link: {e}")
                        import traceback
                        traceback.print_exc()
                
                if not pdf_found_for_article:
                    print(f"    No PDF download link found on article page: {article_url}")
            
            # Save metadata for this page
            save_metadata_per_page(page_metadata, page_num)
            
            if not found_new_articles_on_page and page_num > 1:
                print("No new articles found on this page, stopping pagination.")
                break
            
            page_num += 1
            first_page = False

    except KeyboardInterrupt:
        print("\nScraping interrupted by user.")
    except Exception as e:
        print(f"Unexpected error: {e}")
    finally:
        # Save metadata
        if all_metadata:
            with open(METADATA_FILE, "w", encoding="utf-8") as f:
                json.dump(all_metadata, f, indent=4, ensure_ascii=False)
            print(f"Metadata for {len(all_metadata)} PDFs saved to {METADATA_FILE}")
        else:
            print("No PDFs were downloaded, so no metadata file created.")
        
        # Keep browser open for debugging
        print("Browser window left open for inspection. Close it manually when done.")

if __name__ == "__main__":
    main()
