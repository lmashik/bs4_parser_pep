import logging
import re
from collections import defaultdict
from urllib.parse import urljoin

import requests_cache
from bs4 import BeautifulSoup
from tqdm import tqdm

from configs import configure_argument_parser, configure_logging
from constants import BASE_DIR, EXPECTED_STATUS, MAIN_DOC_URL, MAIN_PEP_URL
from outputs import control_output
from utils import find_tag, get_response
from exceptions import PageLoadException


def whats_new(session):
    whats_new_url = urljoin(MAIN_DOC_URL, 'whatsnew/')
    response = get_response(session, whats_new_url)

    soup = BeautifulSoup(response.text, features='lxml')
    main_div = find_tag(soup, 'section', attrs={'id': 'what-s-new-in-python'})
    div_with_ul = find_tag(main_div, 'div', attrs={'class': 'toctree-wrapper'})
    sections_by_python = div_with_ul.find_all(
        'li', attrs={'class': 'toctree-l1'}
    )
    results = [('Ссылка на статью', 'Заголовок', 'Редактор, Автор')]
    for section in tqdm(sections_by_python):
        version_a_tag = find_tag(section, 'a')
        href = version_a_tag['href']
        version_link = urljoin(whats_new_url, href)
        try:
            response = get_response(session, version_link)
        except PageLoadException:
            continue
        soup = BeautifulSoup(response.text, features='lxml')
        h1 = find_tag(soup, 'h1')
        dl = find_tag(soup, 'dl')
        dl_text = dl.text.replace('\n', ' ')
        results.append((version_link, h1.text, dl_text))

    return results


def latest_versions(session):
    response = get_response(session, MAIN_DOC_URL)

    soup = BeautifulSoup(response.text, features='lxml')
    sidebar = find_tag(soup, 'div', {'class': 'sphinxsidebarwrapper'})
    ul_tags = sidebar.find_all('ul')
    for ul in ul_tags:
        if 'All versions' in ul.text:
            a_tags = ul.find_all('a')
            break
        else:
            raise Exception('Ничего не нашлось')

    results = [('Ссылка на документацию', 'Версия', 'Статус')]
    pattern = r'Python (?P<version>\d\.\d+) \((?P<status>.*)\)'
    for a_tag in a_tags:
        link = a_tag['href']
        text_match = re.search(pattern, a_tag.text)
        version, status = text_match.groups() if text_match else a_tag.text, ''
        results.append(
            (link, version, status)
        )

    return results


def download(session):
    downloads_url = urljoin(MAIN_DOC_URL, 'download.html')
    response = get_response(session, downloads_url)

    soup = BeautifulSoup(response.text, features='lxml')

    main_tag = find_tag(soup, 'div', {'role': 'main'})
    table_tag = find_tag(main_tag, 'table', {'class': 'docutils'})

    pdf_a4_tag = find_tag(
        table_tag,
        'a',
        {'href': re.compile(r'.+pdf-a4\.zip$')}
    )
    pdf_a4_link = pdf_a4_tag['href']
    archive_url = urljoin(downloads_url, pdf_a4_link)

    filename = archive_url.split('/')[-1]

    downloads_dir = BASE_DIR / 'downloads'
    downloads_dir.mkdir(exist_ok=True)
    archive_path = downloads_dir / filename

    response = session.get(archive_url)
    with open(archive_path, 'wb') as file:
        file.write(response.content)

    logging.info(f'Архив был загружен и сохранён: {archive_path}')


def pep(session):
    response = get_response(session, MAIN_PEP_URL)

    soup = BeautifulSoup(response.text, features='lxml')
    pep_numerical_index = find_tag(soup, 'section', {'id': 'numerical-index'})
    tbody_tag = find_tag(pep_numerical_index, 'tbody')
    tr_tags = tbody_tag.find_all('tr')

    mismatched_statuses = []
    results = [('Статус', 'Количество')]
    status_dict = defaultdict(int)
    total = 0

    for tr_tag in tqdm(tr_tags):
        total += 1
        preview_status = tr_tag.abbr.text[1:]
        pep_link = urljoin(MAIN_PEP_URL, find_tag(tr_tag, 'a')['href'])
        try:
            response = get_response(session, pep_link)
        except PageLoadException:
            continue
        soup = BeautifulSoup(response.text, features='lxml')
        dl_tag = find_tag(soup, 'dl', {'class': 'rfc2822 field-list simple'})
        dt_tag_status = (
            dl_tag
            .find(string='Status')
            .find_next_sibling()
            .find_parent()
        )
        dd_next_tag = dt_tag_status.find_next_sibling()
        status = dd_next_tag.abbr.text
        status_dict[status] += 1

        if status not in EXPECTED_STATUS[preview_status]:
            mismatched_statuses.append(
                f'{pep_link}\n'
                f'Статус в карточке: {status}\n'
                f'Ожидаемые статусы: {EXPECTED_STATUS[preview_status]}\n'
            )

    for k, v in status_dict.items():
        results.append((k, v))
    results.append(('Всего (включая неизвестные)', total))

    info = 'Несовпадающие статусы:\n'
    if mismatched_statuses:
        for mismatched_statuse in mismatched_statuses:
            info += mismatched_statuse
        logging.info(info)
    return results


MODE_TO_FUNCTION = {
    'whats-new': whats_new,
    'latest-versions': latest_versions,
    'download': download,
    'pep': pep,
}


def main():
    configure_logging()
    logging.info('Парсер запущен!')

    arg_parser = configure_argument_parser(MODE_TO_FUNCTION.keys())
    args = arg_parser.parse_args()
    logging.info(f'Аргументы командной строки: {args}')
    session = requests_cache.CachedSession()
    if args.clear_cache:
        session.cache.clear()
    parser_mode = args.mode
    results = MODE_TO_FUNCTION[parser_mode](session)

    if results:
        control_output(results, args)

    logging.info('Парсер завершил работу.')


if __name__ == '__main__':
    main()
