"""
The module's functions operate on message bodies trying to extract original
messages (without quoted messages) from html
"""

import regex as re
import html2text
from lxml import html, etree
from copy import deepcopy


RE_FWD = re.compile("(([-]+[ ]*Forwarded message[ ]*[-]+)|(Begin forwarded message:))", re.I | re.M)
CHECKPOINT_PREFIX = '#!%!'
CHECKPOINT_SUFFIX = '!%!#'
CHECKPOINT_PATTERN = re.compile(CHECKPOINT_PREFIX + '\d+' + CHECKPOINT_SUFFIX)

# HTML quote indicators (tag ids)
QUOTE_IDS = ['OLK_SRC_BODY_SECTION']


def add_checkpoint(html_note, counter):
    """Recursively adds checkpoints to html tree.
    checkpoints are added to both text and tail of each tag with DFS ordered counter
    """
    if html_note.text:
        html_note.text = (html_note.text + CHECKPOINT_PREFIX +
                          str(counter) + CHECKPOINT_SUFFIX)
    else:
        html_note.text = (CHECKPOINT_PREFIX + str(counter) +
                          CHECKPOINT_SUFFIX)
    counter += 1

    for child in html_note.iterchildren():
        counter = add_checkpoint(child, counter)

    if html_note.tail:
        html_note.tail = (html_note.tail + CHECKPOINT_PREFIX +
                          str(counter) + CHECKPOINT_SUFFIX)
    else:
        html_note.tail = (CHECKPOINT_PREFIX + str(counter) +
                          CHECKPOINT_SUFFIX)
    counter += 1

    return counter


def delete_quotation_tags(html_note, quotation_checkpoints, placeholder=None):
    """Deletes tags with quotation checkpoints from html tree via depth-first traversal.
        mutates html_note to delete tags
        returns what was deleted
    """
    def recursive_helper(html_note, counter, insert_placeholder):
        # enter node (check text)
        tag_text_in_quotation = quotation_checkpoints[counter]
        if tag_text_in_quotation:
            if insert_placeholder:
                html_note.insert(0, placeholder)
                insert_placeholder = False
            html_note.text = ''

        counter += 1

        # recurse on children
        quotation_children = []  # Children tags which are in quotation.
        for child in html_note.iterchildren():
            if child is placeholder:
                # skip placeholder in recursion
                continue
            child, counter, child_tag_in_quotation = recursive_helper(child, counter, insert_placeholder)
            if child_tag_in_quotation:
                quotation_children.append(child)

        # exit node (check tail)
        tag_tail_in_quotation = quotation_checkpoints[counter]
        if tag_tail_in_quotation:
            if insert_placeholder and not quotation_children:
                html_note.append(placeholder)
                insert_placeholder = False
            html_note.tail = ''

        counter += 1

        # build return structure counter, is_in_quotation
        tag_in_quotation = tag_text_in_quotation and tag_tail_in_quotation

        if tag_in_quotation:
            return html_note, counter, True
        else:
            # Remove quotation children.
            if insert_placeholder and quotation_children:
                quotation_children[0].addprevious(placeholder)
            for child in quotation_children:
                html_note.remove(child)
            return html_note, counter, False

    recursive_helper(html_note, 0, placeholder != None)


def cut_gmail_quote(html_message, placeholder=None):
    ''' Cuts the last outermost blockquote in the outermost element with class gmail_quote. '''
    gmail_quote = html_message.cssselect('.gmail_quote')
   
    if gmail_quote:
        gmail_quote = gmail_quote[0]
        if gmail_quote.text and (re.search(RE_FWD, gmail_quote.text)):
            return False
        if len(gmail_quote) and (re.search(RE_FWD, html.tostring(gmail_quote[0]))):
            return False

        blockquotes = gmail_quote.xpath('//blockquote')
        if blockquotes:
            blockquotes = blockquotes[0].getparent().xpath('./blockquote')
            if len(blockquotes) == 1:
                if placeholder is not None:
                    gmail_quote.addprevious(placeholder)
                gmail_quote.getparent().remove(gmail_quote)
                return True
            if len(blockquotes) > 1:
                if placeholder is not None:
                    blockquotes[-1].addprevious(placeholder)
                blockquotes[-1].getparent().remove(blockquotes[-1])
                return True
            return False
        return False


def cut_microsoft_quote(html_message, placeholder=None):
    ''' Cuts splitter block and all following blocks. '''
    splitter = html_message.xpath(
        #outlook 2007, 2010
        "//div[@style='border:none;border-top:solid #B5C4DF 1.0pt;"
        "padding:3.0pt 0cm 0cm 0cm']|"
        #windows mail
        "//div[@style='padding-top: 5px; "
        "border-top-color: rgb(229, 229, 229); "
        "border-top-width: 1px; border-top-style: solid;']"
    )

    if splitter:
        splitter = splitter[0]
        #outlook 2010
        if splitter == splitter.getparent().getchildren()[0]:
            splitter = splitter.getparent()
    else:
        #outlook 2003
        splitter = html_message.xpath(
            "//div"
            "/div[@class='MsoNormal' and @align='center' "
            "and @style='text-align:center']"
            "/font"
            "/span"
            "/hr[@size='3' and @width='100%' and @align='center' "
            "and @tabindex='-1']"
        )
        if len(splitter):
            splitter = splitter[0]
            splitter = splitter.getparent().getparent()
            splitter = splitter.getparent().getparent()

    if len(splitter):
        parent = splitter.getparent()
        after_splitter = splitter.getnext()
        while after_splitter is not None:
            parent.remove(after_splitter)
            after_splitter = splitter.getnext()
        if placeholder is not None:
            splitter.addprevious(placeholder)
        parent.remove(splitter)
        return True
    return False


def cut_by_id(html_message, placeholder=None):
    found = False
    for quote_id in QUOTE_IDS:
        quote = html_message.cssselect('#{}'.format(quote_id))
        if quote:
            if placeholder is not None:
                quote[0].addprevious(placeholder)
            quote[0].getparent().remove(quote[0])
            return True
    return False


def cut_blockquote(html_message, placeholder=None):
    ''' Cuts blockquote with wrapping elements. '''
    blockquotes = html_message.xpath('//blockquote')
    if blockquotes:
        # get only highest-level blockquotes
        blockquotes = blockquotes[0].getparent().xpath('./blockquote')
        if blockquotes:
            if blockquotes[0].text and (re.search(RE_FWD, blockquotes[0].text)):
                return False
            if blockquotes[0].getprevious() and (re.search(RE_FWD, html.tostring(blockquotes[0].getprevious()))):
                return False
            if blockquotes[0].getparent().text and (re.search(RE_FWD, blockquotes[0].getparent().text)):
                return False
            if len(blockquotes[0]) and (re.search(RE_FWD, html.tostring(blockquotes[0][0]))):
                return False
        if len(blockquotes) == 1:
            if placeholder is not None:
                blockquotes[0].addprevious(placeholder)
            blockquotes[0].getparent().remove(blockquotes[0])
            return True
        if len(blockquotes) > 1:
            if placeholder is not None:
                blockquotes[-1].addprevious(placeholder)
            blockquotes[-1].getparent().remove(blockquotes[-1])
            return True
        return False
    return False
