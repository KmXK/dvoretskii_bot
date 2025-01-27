def format_lined_list[T](items: list[tuple[T, str]], delimiter: str = ". "):
    max_number_item = max(items, key=lambda x: len(str(x[0])))
    max_length = len(str(max_number_item[0]))
    return "\n".join([
        (f"`{str(item[0]).rjust(max_length)}`" + delimiter + item[1]) for item in items
    ])
