from . import controllers
from . import models


def post_init_hook(env):
    """Seed the built-in TRMNL display images as public attachments."""
    env["trmnl.image.seeder"].seed_images()


def uninstall_hook(env):
    """Remove the seeded TRMNL display image attachments on uninstall."""
    env["trmnl.image.seeder"].remove_images()
