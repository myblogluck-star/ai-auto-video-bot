import os
import json
import asyncio
import requests
from pathlib import Path
import subprocess

import edge_tts
from google import genai
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ==========================================
# SETTINGS & PATHS
# ==========================================
OUT = Path("output")
OUT.mkdir(exist_ok=True)

TOPIC = os.getenv("VIDEO_TOPIC", "Daily Motivation and Success Tips")
LANGUAGE = os.getenv("VIDEO_LANGUAGE", "English")
SCENES = int(os.getenv("VIDEO_SCENES", "3"))

PRIVACY = os.getenv("VIDEO_PRIVACY", "private")
CATEGORY = os.getenv("YOUTUBE_CATEGORY_ID", "24")

# Google Gemini Client (Free Tier)
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
gemini_client = genai.Client(api_key=GEMINI_KEY) if GEMINI_KEY else None

# ==========================================
# 1. FREE SCRIPT GENERATION (Gemini Free API)
# ==========================================
def generate_script(topic, language, scenes_count):
    if not gemini_client:
        print("GEMINI_API_KEY missing, using fallback template.")
        return {
            "title": f"Motivation: {topic}",
            "description": f"Inspiring video about {topic}",
            "scenes": [
                {"narration": "Believe in yourself and take action today.", "image_prompt": "cinematic dramatic motivational scene highly detailed"},
                {"narration": "Success requires consistency and continuous hard work.", "image_prompt": "person standing on top of mountain sunset success"},
                {"narration": "Never give up on your dreams.", "image_prompt": "bright golden future glowing path success"}
            ]
        }

    prompt = f"""
    Create a short video script about '{topic}' in {language}.
    Break it down into exactly {scenes_count} short visual scenes.
    Return ONLY a valid JSON object with keys: 'title', 'description', and 'scenes' (a list of dicts with 'narration' and 'image_prompt').
    """
    response = gemini_client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt,
    )
    raw_text = response.text.strip().replace("```json", "").replace("```", "")
    return json.loads(raw_text)

# ==========================================
# 2. FREE AUDIO GENERATION (Edge TTS)
# ==========================================
async def generate_audio_async(text, output_file):
    # En-US Neural Voice (Natural Voice)
    voice = "en-US-ChristopherNeural"
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_file)

def generate_audio(text, output_file):
    asyncio.run(generate_audio_async(text, output_file))

# ==========================================
# 3. FREE IMAGE GENERATION (Pollinations.ai)
# ==========================================
def generate_image(prompt, output_file):
    formatted_prompt = requests.utils.quote(prompt)
    url = f"https://image.pollinations.ai/prompt/{formatted_prompt}?width=1080&height=1920&nologo=true"
    response = requests.get(url, timeout=30)
    if response.status_code == 200:
        with open(output_file, "wb") as f:
            f.write(response.content)
    else:
        raise Exception(f"Failed to generate image: Status {response.status_code}")

# ==========================================
# 4. BUILD VIDEO (FFMPEG)
# ==========================================
def build_scene_video(image_path, audio_path, output_path):
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", str(image_path),
        "-i", str(audio_path),
        "-c:v", "libx264", "-tune", "stillimage",
        "-c:a", "aac", "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-shortest", str(output_path)
    ]
    subprocess.run(cmd, check=True)

def concatenate_videos(video_list, output_path):
    concat_file = OUT / "concat.txt"
    with open(concat_file, "w") as f:
        for v in video_list:
            f.write(f"file '{v.resolve()}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_file),
        "-c", "copy", str(output_path)
    ]
    subprocess.run(cmd, check=True)

# ==========================================
# 5. YOUTUBE UPLOAD
# ==========================================
def upload_to_youtube(video_path, title, description):
    creds_json = os.getenv("YOUTUBE_CREDENTIALS")
    if not creds_json:
        print("Skipping YouTube upload: YOUTUBE_CREDENTIALS secret not found.")
        return

    creds_data = json.loads(creds_json)
    creds = Credentials.from_authorized_user_info(creds_data)
    youtube = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "title": title[:100],
            "description": description,
            "categoryId": CATEGORY
        },
        "status": {
            "privacyStatus": PRIVACY
        }
    }

    media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"Uploaded {int(status.progress() * 100)}%")

    print(f"Video uploaded successfully! Video ID: {response.get('id')}")

# ==========================================
# MAIN EXECUTION
# ==========================================
def main():
    print("--- Starting FREE AI Video Generator ---")
    
    print("Generating script...")
    data = generate_script(TOPIC, LANGUAGE, SCENES)
    print(f"Title: {data['title']}")

    scene_videos = []
    for idx, scene in enumerate(data['scenes']):
        print(f"\nProcessing Scene {idx+1}/{len(data['scenes'])}...")
        
        audio_file = OUT / f"scene_{idx+1}.mp3"
        image_file = OUT / f"scene_{idx+1}.jpg"
        video_file = OUT / f"scene_{idx+1}.mp4"

        print("- Generating speech (Edge TTS Free)...")
        generate_audio(scene['narration'], audio_file)

        print("- Generating image (Pollinations AI Free)...")
        generate_image(scene['image_prompt'], image_file)

        print("- Rendering scene video...")
        build_scene_video(image_file, audio_file, video_file)
        scene_videos.append(video_file)

    final_video = OUT / "final_video.mp4"
    print("\nMerging all scene videos into final output...")
    concatenate_videos(scene_videos, final_video)
    print(f"Final Video Ready at: {final_video}")

    print("\nUploading to YouTube...")
    upload_to_youtube(final_video, data['title'], data['description'])
    print("--- Workflow Completed Successfully ---")

if __name__ == "__main__":
    main()
