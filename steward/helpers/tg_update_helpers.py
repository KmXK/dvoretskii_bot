from telegram import Update


class UnsupportedUpdateType(Exception):
    pass


def get_message(update: Update):
    if update.message:
        return update.message
    elif update.edited_message:
        return update.edited_message
    elif update.callback_query:
        return update.callback_query.message
    raise UnsupportedUpdateType("Unsupported update type")


def get_from_user(update: Update):
    if update.message:
        return update.message.from_user
    elif update.edited_message:
        return update.edited_message.from_user
    elif update.callback_query:
        return update.callback_query.from_user
    elif update.message_reaction:
        return update.message_reaction.user
    raise UnsupportedUpdateType("Unsupported update type")


def split_long_message(text: str, max_length: int = 4096) -> list[str]:
    if len(text) <= max_length:
        return [text]
    
    chunks = []
    offset = 0
    
    while offset < len(text):
        chunk_end = offset + max_length
        
        if chunk_end >= len(text):
            chunks.append(text[offset:])
            break
        
        safe_break_pos = _find_safe_break_position(text, offset, chunk_end, max_length)
        
        if safe_break_pos > offset:
            chunks.append(text[offset:safe_break_pos])
            offset = safe_break_pos
        else:
            chunks.append(text[offset:chunk_end])
            offset = chunk_end
    
    return chunks


def is_valid_markdown(text: str) -> bool:
    code_block_count = text.count("```")
    return code_block_count % 2 == 0


def _find_safe_break_position(text: str, start: int, end: int, max_length: int) -> int:
    if end >= len(text):
        return end
    
    text_before_end = text[:end]
    code_block_count = text_before_end.count("```")
    in_code_block = code_block_count % 2 == 1
    
    if in_code_block:
        closing_backticks = text.find("```", end - 300, min(end + 300, len(text)))
        if closing_backticks != -1:
            return closing_backticks + 3
        
        code_block_start = text.rfind("```", max(0, start - 1000), end)
        if code_block_start != -1:
            last_newline_before_block = text.rfind("\n", max(0, code_block_start - 100), code_block_start)
            if last_newline_before_block > 0:
                return last_newline_before_block + 1
            return code_block_start
    
    last_newline = text.rfind("\n", start, end)
    if last_newline > start + max_length - 200:
        return last_newline + 1
    
    return end
