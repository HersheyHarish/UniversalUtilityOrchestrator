const NAMES = [
  "Harish", "Alex", "Jordan", "Sarah", "Michael",
  "Emma", "David", "Jessica", "Daniel", "Emily",
  "Matthew", "Olivia", "James", "Sophia", "Christopher",
  "Isabella", "Joshua", "Ava", "Andrew", "Mia",
  "Joseph", "Charlotte", "William", "Amelia", "Anthony",
  "Harper", "Ryan", "Evelyn", "Nicholas", "Abigail"
];

export function getUserName(customerId) {
  if (!customerId) return "User";
  
  // Calculate a deterministic hash from the customerId string
  let hash = 0;
  for (let i = 0; i < customerId.length; i++) {
    hash = customerId.charCodeAt(i) + ((hash << 5) - hash);
  }
  
  // Ensure the hash is positive and within the bounds of the array
  const index = Math.abs(hash) % NAMES.length;
  return NAMES[index];
}
