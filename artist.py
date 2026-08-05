import asyncio
import copy

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from gamdlUrl import get_artist_uls
from queues import download_queue, user_in_queue, user_pending_jobs, is_user_busy

test_router = Router()

class MainSates(StatesGroup):
    choosing_type = State()
    choosing_albums = State()

def get_categories_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="💿 Full Albums", callback_data="cat:full_album")],
        [InlineKeyboardButton(text="🎵 Singles", callback_data="cat:singles")],
        [InlineKeyboardButton(text="🎵 Live", callback_data="cat:live")],
        [InlineKeyboardButton(text="🎵 Compilation", callback_data="cat:compilation")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_album_keyboard(items_list: list[dict], selected_indices: list[int]) -> InlineKeyboardMarkup:
    """Dynamically parses and converts raw dictionaries to selectable interactive items."""
    buttons = []

    # Parse dynamic list items
    for idx, item in enumerate(items_list):
        is_selected = idx in selected_indices
        emoji = "🟢" if is_selected else "⚪"
        buttons.append([
            InlineKeyboardButton(text=f"{emoji} {item['name']}", callback_data=f"toggle:{idx}")
        ])

    # Configuration for Select-All feature based on target list length
    all_selected = len(selected_indices) == len(items_list) if items_list else False
    all_text = "❌ Deselect All" if all_selected else "✅ Select All"
    all_action = "deselect_all" if all_selected else "select_all"

    buttons.append([InlineKeyboardButton(text=all_text, callback_data=f"action:{all_action}")])
    buttons.append([
        InlineKeyboardButton(text="⬅️ Back", callback_data="action:back"),
        InlineKeyboardButton(text="🎯 Confirm", callback_data="action:confirm")
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


@test_router.message(Command("artist"))
async def strat_cmd(msg: Message, state: FSMContext, command: CommandObject):
    url = command.args

    if not url:
        await msg.answer(
            "❌ Please provide an Apple Music artist link!\n"
            "Example: `/artist https://music.apple.com/us/artist/...`",
            parse_mode="Markdown"
        )
        return

    try:
        album, singles, live, compilation = await get_artist_uls(url)
    except Exception as e:
        await msg.answer("❌ Failed to parse or fetch data from that URL.")
        print(f"Fetch error: {e}")
        return

    await state.update_data(
        full_album=album,
        singles=singles,
        live=live,
        compilation=compilation,
    )

    await state.set_state(MainSates.choosing_type)

    await msg.answer(
        text="Data parsed successfully! Select the group category you'd like to browse:",
        reply_markup=get_categories_keyboard()
    )

@test_router.callback_query(MainSates.choosing_type, F.data.startswith("cat:"))
async def select_cat(callback:CallbackQuery, state:FSMContext):
    category = callback.data.split(":")[1]
    data = await state.get_data()

    target_items = data.get(category, [])

    if not target_items:
        try:
            await callback.answer("This category is empty for this artist!", show_alert=True)
        except Exception:
            pass
        return

    await state.update_data(active_category=category, selected_indices=[])

    await state.set_state(MainSates.choosing_albums)

    try:
        await callback.message.edit_text(
            text=f"Managing {category.replace('_', ' ').title()}:",
            reply_markup=get_album_keyboard(target_items, [])
        )
    except Exception:
        pass
    try:
        await callback.answer()
    except Exception:
        pass

@test_router.callback_query(MainSates.choosing_albums, F.data.startswith("toggle:"))
async def handle_toggle(callback: CallbackQuery, state: FSMContext):
    clicked_idx = int(callback.data.split(":")[1])

    user_data = await state.get_data()

    category_key = user_data.get("active_category")
    target_item = user_data.get(category_key, [])
    selected = list(user_data.get("selected_indices", []))

    if clicked_idx in selected:
        selected.remove(clicked_idx)
    else:
        selected.append(clicked_idx)

    await state.update_data(selected_indices=selected)

    try:
        await callback.message.edit_reply_markup(
            reply_markup=get_album_keyboard(target_item, selected)
        )
    except Exception:
        pass
    try:
        await callback.answer()
    except Exception:
        pass
    print(clicked_idx, user_data, selected)


@test_router.callback_query(MainSates.choosing_albums, F.data.startswith("action:"))
async def handle_action(callback: CallbackQuery, state: FSMContext):
    action = callback.data.split(":")[1]

    user_data = await state.get_data()
    category_key = user_data.get("active_category")
    target_items = user_data.get(category_key, [])
    selected = list(user_data.get("selected_indices", []))

    if action == "select_all":
        all_indice = list(range(len(target_items)))
        await state.update_data(selected_indices=all_indice)
        try:
            await callback.message.edit_reply_markup(reply_markup=get_album_keyboard(target_items, all_indice))
        except Exception:
            pass

    elif action == "deselect_all":
        await state.update_data(selected_indices=[])
        try:
            await callback.message.edit_reply_markup(reply_markup=get_album_keyboard(target_items, []))
        except Exception:
            pass

    elif action == "back":
        await state.set_state(MainSates.choosing_type)
        try:
            await callback.message.edit_text(
                text="Select the group category you'd like to browse:",
                reply_markup=get_categories_keyboard()
            )
        except Exception:
            pass

    elif action == "confirm":
        if not selected:
            try:
                await callback.answer(text="Please select at least one item!", show_alert=True)
            except Exception:
                pass
            return

        chosen_objects = [target_items[i] for i in selected]
        urls = [item['url'] for item in chosen_objects]
        user_id_local = callback.from_user.id

        if is_user_busy(user_id_local):
            try:
                await callback.answer("⏳ You already have a download task processing!", show_alert=True)
            except Exception:
                pass
            return

        user_in_queue.add(user_id_local)
        user_pending_jobs[user_id_local] = len(urls)
        print(f"llff{urls}")
        for url in urls:
            payload = {
                "url": url,
                "msg": callback.message,
                "user_id": user_id_local,
            }
            await download_queue.put(payload)

        result_text = "Processing selections:\n\n" + "\n".join([f"• {item['name']}" for item in chosen_objects])
        try:
            await callback.message.edit_text(text=result_text)
        except Exception:
            pass
        await state.clear()

    try:
        await callback.answer()
    except Exception:
        pass
