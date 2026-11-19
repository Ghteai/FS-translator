from lxml import etree

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W14_NS = "http://schemas.microsoft.com/office/word/2010/wordml"


def body(xml: str):
    """Parse a fragment of body content into a <w:document> root."""
    return etree.fromstring(
        f'<w:document xmlns:w="{W_NS}" xmlns:w14="{W14_NS}"><w:body>{xml}</w:body></w:document>'
    )


def child_names(el) -> list[str]:
    return [etree.QName(c).localname for c in el if isinstance(c.tag, str)]


def texts(root) -> list[str]:
    return [t.text or "" for t in root.iter(f"{{{W_NS}}}t")]
