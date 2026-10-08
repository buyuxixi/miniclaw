"""Bounded, deterministic pages shared by project and content catalogs."""
def bounds(page, page_size, total):
    if type(page) is not int or page < 1 or type(page_size) is not int or not 1 <= page_size <= 100:
        raise ValueError('页码需为正整数，每页最多100条')
    page=min(page,max(1,(total+page_size-1)//page_size))
    return page,(page-1)*page_size
