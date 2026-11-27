from django.core.management.base import BaseCommand
from apps.core.models import Campus


CAMPUS_DIRECTORY = [
    ("NASENI Innovation Hub", "Abuja (FCT)", "No. 17, M.S. Haruna Avenue, Idu Industrial Area, P.M.B 391, Garki, Abuja"),
    ("LEEF Centre", "Benue", "Old Makurdi Road, Off Burnt Bricks, near St. Helen's Hospital, Otukpo"),
    ("Kinplus Technologies", "Ekiti", "1st & 2nd Floor, Christore Building, Opp. Crunchies (around State Hospital), Similoluwa, Ado-Ekiti"),
    ("MalHub", "Kwara", "1 Ilofa Road, GRA, Ilorin"),
    ("Pier Place", "Lagos", "14 Montgomery Road, Yaba, Lagos"),
    ("nHub Jos", "Plateau", "TAEN Business Complex, Jos"),
    ("CTEC", "Rivers", "18 Tombia Street, GRA, Port Harcourt"),
    ("SAIL Innovation Lab", "Lagos", "1, Muba Abiru Street, Ikorodu, Lagos"),
    ("SAIL STEM Lab", "Lagos", "1, Muba Abiru Street, Ikorodu, Lagos"),
    ("Ilorin Innovation Hub", "Kwara", "Ahmadu Bello Way, Ilorin"),
]


class Command(BaseCommand):
    help = "Add the Learn2Earn campus directory; existing campus records are left unchanged."

    def handle(self, *args, **options):
        created = 0
        for name, state, address in CAMPUS_DIRECTORY:
            campus, was_created = Campus.objects.get_or_create(
                name=name,
                defaults={"address": f"{address}, {state}", "timezone": "Africa/Lagos", "active": True},
            )
            created += was_created
            if not was_created and not campus.address:
                campus.address = f"{address}, {state}"
                campus.save(update_fields=["address"])
        self.stdout.write(self.style.SUCCESS(
            f"Campus directory ready: {len(CAMPUS_DIRECTORY)} entries ({created} newly created)."
        ))
