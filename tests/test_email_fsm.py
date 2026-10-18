import unittest
from email_fsm import (begin_email, accept_email, mark_email_verified,
                       confirm_email_delivery, normalize_email,
                       STATE_CHOOSE_DELIVERY, STATE_WAITING_FOR_EMAIL,
                       STATE_VERIFY_EMAIL, STATE_CONFIRM_EMAIL,
                       STATE_DELIVERY_QUEUED)

DATA = {"selected_book": {"id": "b1", "title": "Book"}}


class EmailFSMTests(unittest.TestCase):
    def test_begin(self):
        state, data = begin_email(STATE_CHOOSE_DELIVERY, DATA)
        self.assertEqual(state, STATE_WAITING_FOR_EMAIL)
        self.assertEqual(data["selected_book"]["id"], "b1")

    def test_invalid_address_preserves_state(self):
        result = accept_email(STATE_WAITING_FOR_EMAIL, DATA, "not-an-email")
        self.assertFalse(result["ok"])
        self.assertEqual(result["state"], STATE_WAITING_FOR_EMAIL)

    def test_valid_address_requires_verification(self):
        result = accept_email(STATE_WAITING_FOR_EMAIL, DATA, "Me@Example.COM")
        self.assertEqual(result["state"], STATE_VERIFY_EMAIL)
        self.assertEqual(result["data"]["pending_email"], "Me@example.com")

    def test_reject_unverified_confirmation(self):
        with self.assertRaises(ValueError):
            confirm_email_delivery(STATE_VERIFY_EMAIL, DATA, confirmed=True,
                                   enqueue_job=lambda *a: "job1")

    def test_verified_flow_queues(self):
        result = accept_email(STATE_WAITING_FOR_EMAIL, DATA, "a@example.com")
        state, data = mark_email_verified(result["state"], result["data"],
            verified_address="a@example.com", verification_evidence="trusted-verification-id")
        self.assertEqual(state, STATE_CONFIRM_EMAIL)
        state, result_data = confirm_email_delivery(state, data, confirmed=True,
            enqueue_job=lambda book, email: "job-123")
        self.assertEqual(state, STATE_DELIVERY_QUEUED)
        self.assertEqual(result_data["delivery_job_id"], "job-123")

    def test_no_confirmation(self):
        result = accept_email(STATE_WAITING_FOR_EMAIL, DATA, "a@example.com")
        state, data = mark_email_verified(result["state"], result["data"],
            verified_address="a@example.com", verification_evidence="trusted")
        with self.assertRaises(PermissionError):
            confirm_email_delivery(state, data, confirmed=False,
                                   enqueue_job=lambda *a: "job1")

    def test_no_verification_evidence(self):
        result = accept_email(STATE_WAITING_FOR_EMAIL, DATA, "a@example.com")
        with self.assertRaises(PermissionError):
            mark_email_verified(result["state"], result["data"],
                verified_address="a@example.com", verification_evidence=None)

    def test_address_validation(self):
        self.assertIsNone(normalize_email("a@@example.com"))
        self.assertIsNone(normalize_email("bad\naddress@example.com"))
        self.assertEqual(normalize_email("  a@example.com "), "a@example.com")


if __name__ == "__main__":
    unittest.main()
