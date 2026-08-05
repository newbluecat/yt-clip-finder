import services.downloader

if __name__ == "__main__":
    url: str = services.downloader.build_playlist_ytdlp_url(
        "PLrMS357ieiqS894xcyXj2wwG8H05Rutvo",
    )
    print(services.downloader.fetch_records(url))
