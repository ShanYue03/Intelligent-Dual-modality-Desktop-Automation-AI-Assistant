import logoImage from "../../assets/LogoRounded.png";

export function FridayIcon() {
  return (
    <div className="w-10 h-10 rounded-xl overflow-hidden shrink-0">
      <img src={logoImage} alt="Friday Logo" className="w-full h-full object-cover" />
    </div>
  );
}
