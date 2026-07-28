from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class ExternalLinkTitleMigrationTests(TransactionTestCase):
    migrate_from = ("core", "0005_mediavote")
    migrate_to = (
        "core",
        "0006_contactmessage_alter_evenementmedia_options_and_more",
    )

    def setUp(self):
        super().setUp()
        self.executor = MigrationExecutor(connection)
        self.executor.migrate([self.migrate_from])
        old_apps = self.executor.loader.project_state([self.migrate_from]).apps
        old_apps.get_model("core", "ExternalLink").objects.create(
            slug="boutique-goodies",
            label="Boutique du JOY",
            url="https://example.com/boutique",
        )

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_preserves_existing_label_as_title(self):
        self.executor = MigrationExecutor(connection)
        self.executor.migrate([self.migrate_to])
        new_apps = self.executor.loader.project_state([self.migrate_to]).apps

        link = new_apps.get_model("core", "ExternalLink").objects.get(
            slug="boutique-goodies"
        )

        self.assertEqual(link.titre, "Boutique du JOY")
