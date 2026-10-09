from django.core.management.base import BaseCommand, CommandError

from board.models import User


class Command(BaseCommand):
    help = "Create the first administrator with the required initial password."

    def add_arguments(self, parser):
        parser.add_argument("--username", default="admin")
        parser.add_argument("--name", default="管理员")

    def handle(self, *args, **options):
        if User.objects.filter(is_superuser=True).exists():
            raise CommandError("An administrator already exists.")

        username = options["username"]
        if User.objects.filter(username=username).exists():
            raise CommandError(f"The username {username!r} already exists.")

        User.objects.create_superuser(
            username=username,
            email="",
            password="123456",
            display_name=options["name"],
            must_change_password=True,
        )
        self.stdout.write(self.style.SUCCESS(f"Created administrator {username!r}. Initial password: 123456"))
