package rs2;

public class Censor {
  
  private static char[] fragments = new char[100];
  
  public static String method409(String s) {
    char[] ac = s.toLowerCase().toCharArray();
    char[] ac1 = {'a', 'b', 'c'};
    int j = 1;
    int k;
/*  209 */     for (k = 0; k <= ac.length - ac1.length; k += j) {
      // Search logic here
      boolean flag = true;
      for (int l = 0; l < ac1.length; l++) {
        if (ac[k + l] != ac1[l]) {
          flag = false;
          break;
        }
      }
      if (flag) {
        // Found match
        for (int i1 = 0; i1 < ac1.length; i1++) {
          ac[k + i1] = '*';
        }
      }
    }
    return new String(ac);
  }
  
  public static String method410(String s) {
    char[] ac3 = s.toLowerCase().toCharArray();
    char[] ac1 = {'x', 'y', 'z'};
    int j = 1;
    int k;
/*  331 */     for (k = 0; k <= ac3.length - ac1.length; k += j) {
      // Another search logic
      boolean flag = true;
      for (int l = 0; l < ac1.length; l++) {
        if (ac3[k + l] != ac1[l]) {
          flag = false;
          break;
        }
      }
      if (flag) {
        for (int i1 = 0; i1 < ac1.length; i1++) {
          ac3[k + i1] = '*';
        }
      }
    }
    return new String(ac3);
  }
  
  public static void method411() {
    int l1 = 5;
/*  412 */           if (l1 > 2) {
              // Missing closing brace here causes "reached end of file while parsing"
              System.out.println("Value is greater than 2");
            // } <- This brace is missing, causing parser error
  
  // End of file - missing closing braces for the method and class
}
