from tfmkt.spiders.common import BaseSpider
from scrapy.shell import inspect_response # required for debugging
from inflection import parameterize, underscore
from urllib.parse import urlparse

def decode_value(val: str) -> str:
    result = val or ""
    if isinstance(val, str):
        result = result.strip().encode("ascii", "ignore")
        result = result.decode()
        return result
    return result

class TransfersSpider(BaseSpider):
  """
  parent=competitions
  """
  name = 'transfers'

  def parse(self, response, parent):
    """Parse player transfer attributes and fetch "full stats" URL

    @url https://www.transfermarkt.co.uk/major-league-soccer/startseite/wettbewerb/MLS1
    @returns requests 1 1
    @cb_kwargs {"parent": "dummy"}
    """

    try:
        all_transfers_href = response.xpath('//a[contains(text(),"View complete list")]/@href').get()
        detailed_transfers_href = all_transfers_href + f"/plus/1"

        yield response.follow(detailed_transfers_href, self.parse_transfers, cb_kwargs={'parent': parent})
    except:
        pass

  def parse_transfers(self, response, parent):
    """Parse player's full stats. From this page we collect all player appearances

    @url https://www.transfermarkt.co.uk/sergio-aguero/leistungsdaten/spieler/26399/plus/0?saison=2020
    @returns items 9
    @cb_kwargs {"parent": "dummy"}
    @scrapes assists competition_code date for goals href matchday minutes_played opponent parent pos red_cards result second_yellow_cards type venue yellow_cards
    """

    # inspect_response(response, self)
    # exit(1)

    def parse_transfers_table(table):
        """Parses a table of player's statistics."""
        header_text_elements = [
            self.safe_strip(header_text.css("a::text").get() or header_text.css("::text").get())
            for header_text in table.css("th")
        ]
        header_elements = [
            underscore(parameterize(header))
            for header in header_text_elements
        ]
        header_elements.insert(1, "position")

        value_elements_matrix = []
        for row in table.css('tr')[:2]:
            value_elements = []

            if not len(row.css('td').getall()) > 6:
                continue

            for data_idx, element in enumerate(row.xpath('td')):
                has_multi_rows = len(element.css('tr')) > 1

                if has_multi_rows:
                    for inner_row in element.css('tr'):
                        elements_to_parse = inner_row.xpath('td[@rowspan]') if data_idx > 0 else inner_row.xpath('td[not(@rowspan)]')
                        for inner_data in elements_to_parse:
                            # Parse the team to/from
                            if inner_data.css('img.tiny_wappen::attr(title)').get():
                                team = decode_value(
                                    inner_data.css('img.tiny_wappen::attr(title)').get()
                                )
                                value_elements.append(team)
                            # Parse everything else
                            else:
                                value_elements.append(parse_transfer_element(inner_data))
                else:
                    # Parse the nation
                    if element.css('img.flaggenrahmen::attr(title)').get():
                        nation = decode_value(element.css('img.flaggenrahmen::attr(title)').get())
                        value_elements.append(nation)
                    elif parse_transfer_element(element) is not None:
                        value_elements.append(parse_transfer_element(element))

            if len(value_elements) > 0:
                value_elements_matrix.append(value_elements)

        for value_elements in value_elements_matrix:
          header_elements_len = len(header_elements)
          value_elements_len = len(value_elements)
          assert(header_elements_len == value_elements_len), f"Header ({header_elements}) - cell element ({value_elements}) mismatch at {response.url}"
          yield dict(zip(header_elements, value_elements))

    def parse_transfer_element(elem):
        """Parse an individual table cell"""

        self.logger.debug("Parsing element: %s", elem.get())

        # some cells include the club classification in the national league in brackets. for example, "Leeds (10.)"
        # these are at the same time unncessary and annoying to parse, as club information can be obtained
        # from the "shield" image. identify these cells by looking for descendents of the class 'tabellenplatz'
        has_classification_in_brackets = elem.xpath('*[@class = "tabellenplatz"]').get() is not None
        # club information is parsed from team "shields" using a separate logic from the rest
        # identify cells containing club shields
        has_shield_class = elem.css('img::attr(src)').get() is not None
        club_href = elem.xpath('a[contains(@href, "spielplan/verein")]/@href').get()
        result_href = elem.css('a.ergebnis-link::attr(href)').get()
        
        self.logger.debug("Extracted values: has_shield_class: %s, club_href: %s, result_href: %s", has_shield_class, club_href, result_href)
        
        if (
            (has_classification_in_brackets and club_href is None) or
            (club_href is not None and not has_shield_class)
        ):
          self.logger.debug("Found club href without shield class, skipping")
          return None
        elif club_href is not None:
          self.logger.debug("Found club href: %s", club_href)
          return {'type': 'club', 'href': club_href}
        elif result_href is not None:
          self.logger.debug("Found result/game href: %s", result_href)
          return {'type': 'game', 'href': result_href}
        # finally, most columns can be parsed by extracting the text at the element's "last leaf"
        else:
          extracted_element = decode_value(elem.xpath('string(.)').get().strip().replace('"', ''))
          self.logger.debug("Extracted element: %s", extracted_element)
          return extracted_element

    competition_name = decode_value(response.css('header.data-header > div > h1::text').get().strip())
    self.logger.info("competition: %s", competition_name)
    transfer_table = response.css('table.items')

    all_transfers = {}
    for table in transfer_table:
      transer_data = list(parse_transfers_table(table))
      all_transfers[competition_name] = transer_data

    url = urlparse(response.url).path
    for competition_name, transfers in all_transfers.items():
        self.logger.info("Transfers count: %s", len(transfers))
        for transfer in transfers:
            yield {
                'type': 'transfer',
                'href': url,
                'parent': parent,
                'competition_code': competition_name,
                **transfer
            }
