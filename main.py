import downloader

if __name__ == "__main__":
    url: str = downloader._build_playlist_ytdlp_url(
        "PLrMS357ieiqS894xcyXj2wwG8H05Rutvo",
    )
    print(downloader._get_records(url))
