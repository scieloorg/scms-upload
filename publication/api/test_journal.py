from unittest import TestCase

from publication.api.journal import JournalPayload


class JournalPayloadCleanBrTagsTest(TestCase):
    def test_clean_br_tags_removes_br(self):
        result = JournalPayload._clean_br_tags(
            "PO Box 339, <br>Bloemfontein, Free State"
        )
        self.assertEqual(result, "PO Box 339, Bloemfontein, Free State")

    def test_clean_br_tags_removes_br_self_closing(self):
        result = JournalPayload._clean_br_tags(
            "PO Box 339, <br/>Bloemfontein, Free State"
        )
        self.assertEqual(result, "PO Box 339, Bloemfontein, Free State")

    def test_clean_br_tags_removes_br_self_closing_with_space(self):
        result = JournalPayload._clean_br_tags(
            "PO Box 339, <br />Bloemfontein, Free State"
        )
        self.assertEqual(result, "PO Box 339, Bloemfontein, Free State")

    def test_clean_br_tags_case_insensitive(self):
        result = JournalPayload._clean_br_tags(
            "PO Box 339, <BR>Bloemfontein, <Br>Free State"
        )
        self.assertEqual(result, "PO Box 339, Bloemfontein, Free State")

    def test_clean_br_tags_without_surrounding_comma(self):
        result = JournalPayload._clean_br_tags(
            "Address Line 1<br>Address Line 2"
        )
        self.assertEqual(result, "Address Line 1, Address Line 2")

    def test_clean_br_tags_multiple(self):
        result = JournalPayload._clean_br_tags(
            "Avenida Dr. Arnaldo, 715<br>01246-904 São Paulo SP Brazil<br>Tel./Fax: +55 11 3061-7985"
        )
        self.assertEqual(
            result,
            "Avenida Dr. Arnaldo, 715, 01246-904 São Paulo SP Brazil, Tel./Fax: +55 11 3061-7985",
        )

    def test_clean_br_tags_no_tags(self):
        result = JournalPayload._clean_br_tags(
            "Rua Leopoldo Bulhões, 1480, Rio de Janeiro"
        )
        self.assertEqual(result, "Rua Leopoldo Bulhões, 1480, Rio de Janeiro")

    def test_clean_br_tags_none(self):
        result = JournalPayload._clean_br_tags(None)
        self.assertIsNone(result)

    def test_clean_br_tags_empty(self):
        result = JournalPayload._clean_br_tags("")
        self.assertEqual(result, "")

    def test_clean_br_tags_real_world_example(self):
        """Test with the exact pattern from the issue screenshot."""
        result = JournalPayload._clean_br_tags(
            "Centre for Gender and Africa Studies, University of the Free State, "
            "PO Box 339, <br>Bloemfontein, Free State, ZA, 9300, "
            "<br>Tel: +27 (0)82 384 7027 - E-mail: henning.melber@nai.uu.se"
        )
        self.assertEqual(
            result,
            "Centre for Gender and Africa Studies, University of the Free State, "
            "PO Box 339, Bloemfontein, Free State, ZA, 9300, "
            "Tel: +27 (0)82 384 7027 - E-mail: henning.melber@nai.uu.se",
        )


class JournalPayloadAddContactTest(TestCase):
    def test_add_contact_strips_br_from_address(self):
        payload = {}
        builder = JournalPayload(payload)
        builder.add_contact(
            name="Test Publisher",
            email="test@example.com",
            address="Street 1, <br>City, <br>Country",
            city="City",
            state="State",
            country="Country",
        )
        self.assertEqual(
            payload["contact"]["address"],
            "Street 1, City, Country",
        )

    def test_add_contact_without_br(self):
        payload = {}
        builder = JournalPayload(payload)
        builder.add_contact(
            name="Test Publisher",
            email="test@example.com",
            address="Street 1, City, Country",
            city="City",
            state="State",
            country="Country",
        )
        self.assertEqual(
            payload["contact"]["address"],
            "Street 1, City, Country",
        )

    def test_add_contact_none_address(self):
        payload = {}
        builder = JournalPayload(payload)
        builder.add_contact(
            name="Test Publisher",
            email="test@example.com",
            address=None,
            city="City",
            state="State",
            country="Country",
        )
        self.assertIsNone(payload["contact"]["address"])
