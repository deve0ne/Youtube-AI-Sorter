from openai import OpenAI
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
import logging


logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

with open('categories.txt', 'r') as file:
    categories = file.read().splitlines()

with open('openai_api_key.txt', 'r') as file:
    openai_api_key = file.read().strip()

# This scope allows for full read/write access to the authenticated user's account.
SCOPES = ['https://www.googleapis.com/auth/youtube.force-ssl']


def get_authenticated_service():
    flow = InstalledAppFlow.from_client_secrets_file(
        'client_secrets.json', SCOPES)
    credentials = flow.run_local_server()
    return build('youtube', 'v3', credentials=credentials)


youtube = get_authenticated_service()

system_promt = f"""
You are a professional YouTube video classifier based on its title and tags. You have a set of video categories:
{categories}

Your task is to assign videos to one of these categories. If a video fits into multiple categories, choose the one that is listed first. If you are absolutely sure that the video does not fit into any of the categories, assign it the category Unsorted. Use this category only in extreme cases.

Input: The user will provide you with a list of videos, each line is a separate video. The title comes first, followed by a semicolon and then the tags.

Output: You should respond with a list of assigned categories and nothing more. Do not write the names of the videos themselves. No other information is allowed in the output, and formatting and markdown are prohibited.
"""


def classify_videos(titles_with_tags, categories):
    client = OpenAI(api_key=openai_api_key)
    all_responses = []
    try:
        # Разбиваем список на пакеты по 10 видео
        batch_size = 50
        for i in range(0, len(titles_with_tags), batch_size):
            batch_titles_with_tags = titles_with_tags[i:i+batch_size]
            titles_message = "\n".join(batch_titles_with_tags)
            messages = [{"role": "system", "content": system_promt},
                        {"role": "user", "content": titles_message}]

            print(messages)

            completion = client.chat.completions.create(
                temperature=0.5,
                model="gpt-4-0125-preview",
                messages=messages,
                max_tokens=80 * len(batch_titles_with_tags),
            )
            response = completion.choices[0].message.content
            print(response)
            # Предполагается, что ответ будет содержать категории, разделенные новой строкой
            responses = response.strip().split('\n')
            all_responses.extend(responses)
            for title_with_tags, category in zip(batch_titles_with_tags, responses):
                video_title = title_with_tags.split(';')[0]  # Извлекаем название видео
                logging.info(f"{video_title} - {category}")  # Логируем название видео и категорию

        return all_responses
    except Exception as e:
        logging.error(f"Failed to classify video titles: {e}")
        return [None] * len(titles_with_tags)

def get_or_create_playlist_id(category_name):
    # Проверяем, существует ли уже плейлист
    playlists_request = youtube.playlists().list(part='snippet', mine=True)
    playlists_response = playlists_request.execute()
    for playlist in playlists_response.get('items', []):
        if playlist['snippet']['title'] == category_name:
            return playlist['id']
    # Если плейлист не найден, создаем новый
    create_playlist_request = youtube.playlists().insert(
        part='snippet,status',
        body={
            'snippet': {
                'title': category_name,
                'description': f'Playlist for category {category_name}',
                'tags': ['YouTube', 'API', 'Automatically generated'],
                'defaultLanguage': 'en'
            },
            'status': {
                'privacyStatus': 'private'
            }
        }
    )
    create_playlist_response = create_playlist_request.execute()
    return create_playlist_response['id']


def add_video_to_playlist(video_id, playlist_id):
    youtube.playlistItems().insert(
        part='snippet',
        body={
            'snippet': {
                'playlistId': playlist_id,
                'resourceId': {
                    'kind': 'youtube#video',
                    'videoId': video_id
                }
            }
        }
    ).execute()


# Получаем видео из плейлиста "To Sort" и их теги
to_sort_request = youtube.playlistItems().list(
    part='snippet,contentDetails',
    playlistId='PL44Lz6z_z_5LRjybhzDEDsXOgjWonLVib',  # ID плейлиста "To Sort"
    maxResults=10
)
to_sort_response = to_sort_request.execute()
titles_with_tags = []
video_ids = []

# Собираем ID видео для запроса тегов
for item in to_sort_response.get('items', []):
    video_ids.append(item['contentDetails']['videoId'])

# Получаем теги для каждого видео
video_tags_request = youtube.videos().list(
    part='snippet',
    id=','.join(video_ids)
)
video_tags_response = video_tags_request.execute()

# Сопоставляем теги с названиями видео
for item in video_tags_response.get('items', []):
    video_title = item['snippet']['title']
    video_tags = item['snippet'].get('tags', [])  # Используем метод get для обработки отсутствия тегов
    title_with_tags = f"{video_title}; {', '.join(video_tags)}"
    titles_with_tags.append(title_with_tags)

categories = classify_videos(titles_with_tags, categories)

for video_id, category in zip(video_ids, categories):
    if category:
        playlist_id = get_or_create_playlist_id(category)
        add_video_to_playlist(video_id, playlist_id)
        # youtube.playlistItems().delete(
        #     id=item['id']
        # ).execute()
